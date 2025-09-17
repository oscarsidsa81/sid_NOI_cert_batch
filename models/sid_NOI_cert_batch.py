# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import io, base64, zipfile
from PyPDF2 import PdfFileWriter, PdfFileReader
from reportlab.pdfgen import canvas


class StockPickingBatch(models.Model):
    _inherit = 'stock.picking.batch'

    # Opcional: flags a nivel batch (puedes omitirlos si no quieres estado en lote)
    certificate_add_watermark = fields.Boolean(
        string='Añadir Marca de agua (Batch)?', default=True
    )
    document_attachment_id = fields.Many2one('ir.attachment', string='Adjunto (Batch)')

    # -------------------------------------------------------------------------
    # UTILIDADES (reuso 1:1 de tu lógica, adaptado a batch)
    # -------------------------------------------------------------------------
    def add_watermark(self, pdf_file, watermark_text):
        try:
            watermark = PdfFileReader(io.BytesIO(base64.b64decode(pdf_file)) if isinstance(pdf_file, str) else io.BytesIO(pdf_file))
            output_pdf = PdfFileWriter()

            for page_num in range(watermark.getNumPages()):
                page = watermark.getPage(page_num)
                page_width = float(page.mediaBox.getWidth())
                page_height = float(page.mediaBox.getHeight())
                rotation = page.get('/Rotate') or 0

                # dividir texto (dos líneas máx)
                watermark_text_lines = (watermark_text or "").split("\n")
                watermark_line1 = watermark_text_lines[0] if watermark_text_lines else ""
                watermark_line2 = watermark_text_lines[1] if len(watermark_text_lines) > 1 else ""

                # dibujar watermark
                watermark_canvas = io.BytesIO()
                c = canvas.Canvas(watermark_canvas, pagesize=(page_width, page_height))
                c.setFont("Helvetica", 10)
                c.setFillGray(0.2)

                text_x_position = 10
                text_y_position = 20

                if rotation == 90:
                    c.translate(page_height, 0)
                    c.rotate(90)
                elif rotation == 180:
                    c.translate(page_width, page_height)
                    c.rotate(180)
                elif rotation == 270:
                    c.translate(0, page_width)
                    c.rotate(270)

                if watermark_line1:
                    c.drawString(text_x_position, text_y_position, watermark_line1)
                if watermark_line2:
                    c.drawString(text_x_position, text_y_position - 12, watermark_line2)

                c.save()

                watermark_pdf = PdfFileReader(io.BytesIO(watermark_canvas.getvalue()))
                watermark_page = watermark_pdf.getPage(0)
                page.mergePage(watermark_page)
                output_pdf.addPage(page)

            output_stream = io.BytesIO()
            output_pdf.write(output_stream)
            return output_stream.getvalue()

        except Exception as e:
            raise UserError(
                _("Ocurrió un error al intentar modificar el PDF. "
                  "Por favor, compruebe que no está dañado.\nError: %s") % e
            )

    def _update_or_create_document_batch(self, attachment_id):
        """Crea/actualiza el Document para el lote (no en el picking)."""
        self.ensure_one()
        values = {
            'folder_id': self.env.ref('oct_certificate_management.documents_certificate_done_folder').id,
            'owner_id': self.create_uid.id,
            # Nota: partner_id es ambiguo en lote (puede haber varios clientes)
            # Si tus lotes son homogéneos en cliente, podrías poner:
            # 'partner_id': self.picking_ids[:1].partner_id.id if self.picking_ids else False,
        }
        Documents = self.env['documents.document'].with_context(default_type='empty').sudo()
        doc = Documents.search([('attachment_id', '=', attachment_id)], limit=1)
        if doc:
            doc.write(values)
            document = doc
        else:
            values.update({'attachment_id': attachment_id})
            document = Documents.create(values)
        return document

    @staticmethod
    def convert_multiple_base64_to_pdf_and_zip(pdf_bytes_list, pdf_filenames):
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for pdf_bytes, pdf_filename in zip(pdf_bytes_list, pdf_filenames):
                # pdf_bytes puede venir en bytes ya “limpios”
                pdf_stream = io.BytesIO(pdf_bytes)
                pdf_reader = PdfFileReader(pdf_stream)
                pdf_writer = PdfFileWriter()
                for page_num in range(pdf_reader.getNumPages()):
                    pdf_writer.addPage(pdf_reader.getPage(page_num))
                output_pdf_stream = io.BytesIO()
                pdf_writer.write(output_pdf_stream)
                output_pdf_stream.seek(0)
                zip_file.writestr(pdf_filename, output_pdf_stream.read())
        zip_data = zip_buffer.getvalue()
        return base64.b64encode(zip_data).decode('utf-8')

    # -------------------------------------------------------------------------
    # ACCIÓN 1: PDF ÚNICO (MERGED) EN EL LOTE
    # -------------------------------------------------------------------------
    def action_print_merged_report_batch(self):
        """
        Genera un único PDF con:
        - (opcional) el informe de cada picking del lote (delivery report)
        - cada certificado de cada línea del lote (con watermark)
        Lo adjunta al lote y crea/actualiza su Document.
        """
        self.ensure_one()

        def append_pdf(input_reader, output_writer):
            [output_writer.addPage(input_reader.getPage(n)) for n in range(input_reader.getNumPages())]

        output = PdfFileWriter()

        # Si quieres incluir el informe de cada albarán antes de los certificados (como en tu acción)
        for picking in self.picking_ids:
            # Render del QWeb del albarán
            picking_pdf_bytes = self.env.ref('stock_picking_batch.action_report_picking_batch')._render_qweb_pdf(picking.ids)[0]
            append_pdf(PdfFileReader(io.BytesIO(picking_pdf_bytes)), output)

            # Certificados por línea de movimiento
            for line in picking.move_line_ids:
                origin = line.move_id._get_source_document()
                for certificate in line.with_context(active_test=False).certificate_ids:
                    if certificate.certificate_file:
                        # Marca de agua: puedes tomar el flag del lote o del picking
                        add_wm = self.certificate_add_watermark if self.certificate_add_watermark is not None else True
                        wm_text = ""
                        if add_wm:
                            wm_text = (
                                "SIDSA: %s  Cliente: %s N°Pedido: %s \n Albarán: %s Item: %s Cantidad: %s Colada: %s"
                                % (
                                    origin.name if origin else "",
                                    origin.partner_id.name if origin and origin.partner_id else picking.partner_id.name or "",
                                    getattr(origin, 'client_order_ref', "") if origin else "",
                                    picking.name or "",
                                    line.move_id.item or "",
                                    line.qty_done or line.product_uom_qty or 0,
                                    line.lot_id.name or ""
                                )
                            )
                        cert_wm_bytes = self.add_watermark(certificate.certificate_file, wm_text)
                        append_pdf(PdfFileReader(io.BytesIO(cert_wm_bytes)), output)

        # Guardar y adjuntar
        output_stream = io.BytesIO()
        output.write(output_stream)

        attachment_vals = {
            'name': _("Certificados Lote - %s") % (self.name or self.id),
            'datas': base64.encodebytes(output_stream.getvalue()),
            'res_model': 'stock.picking.batch',
            'res_id': self.id,
            'type': 'binary',
            'mimetype': 'application/pdf',
        }
        attachment = self.env['ir.attachment'].sudo().create(attachment_vals)
        self.document_attachment_id = attachment

        document = self._update_or_create_document_batch(attachment.id)

        self.message_post(
            body=_("Certificados (PDF) generados para el lote: %s") % (attachment.name),
            attachment_ids=[attachment.id],
            author_id=self.env.user.partner_id.id
        )
        return True

    # -------------------------------------------------------------------------
    # ACCIÓN 2: ZIP CON PDFs SEPARADOS EN EL LOTE
    # -------------------------------------------------------------------------
    def action_zip_certificates_batch(self):
        """
        Genera un ZIP con:
        - Un PDF por albarán (delivery report)
        - Un PDF por certificado (con watermark) nombrado por certificado + item
        Lo adjunta al lote y crea/actualiza su Document.
        """
        self.ensure_one()

        pdf_lists, pdf_filenames = [], []

        for picking in self.picking_ids:
            # Albarán PDF
            picking_pdf_bytes = self.env.ref('stock_picking_batch.action_report_picking_batch')._render_qweb_pdf(picking.ids)[0]
            pdf_lists.append(picking_pdf_bytes)
            pdf_filenames.append(("%s.pdf" % (picking.name or str(picking.id))).replace("/", "-"))

            # Certificados por línea
            for line in picking.move_line_ids:
                origin = line.move_id._get_source_document()
                for certificate in line.with_context(active_test=False).certificate_ids:
                    if certificate.certificate_file:
                        add_wm = self.certificate_add_watermark if self.certificate_add_watermark is not None else True
                        wm_text = ""
                        if add_wm:
                            wm_text = (
                                "SIDSA: %s  Cliente: %s N°Pedido: %s \n Albarán: %s Item: %s Cantidad: %s Colada: %s"
                                % (
                                    origin.name if origin else "",
                                    origin.partner_id.name if origin and origin.partner_id else picking.partner_id.name or "",
                                    getattr(origin, 'client_order_ref', "") if origin else "",
                                    picking.name or "",
                                    line.move_id.item or "",
                                    line.qty_done or line.product_uom_qty or 0,
                                    line.lot_id.name or ""
                                )
                            )
                        cert_wm_bytes = self.add_watermark(certificate.certificate_file, wm_text)
                        pdf_lists.append(cert_wm_bytes)
                        pdf_filenames.append("%s-%s.pdf" % ((certificate.name or "CERT"), (line.move_id.item or "")))

        try:
            b64_zip_files = self.convert_multiple_base64_to_pdf_and_zip(pdf_lists, pdf_filenames)
        except Exception as e:
            raise UserError(
                _("Ocurrió un error al intentar crear el comprimido. "
                  "Por favor, compruebe que los PDFs no estén dañados. \n Error: %s") % e
            )

        attachment_vals = {
            'name': _("Certificados Lote (ZIP) - %s") % (self.name or self.id),
            'datas': b64_zip_files,
            'res_model': 'stock.picking.batch',
            'res_id': self.id,
            'type': 'binary',
            'mimetype': 'application/zip',
        }
        attachment = self.env['ir.attachment'].sudo().create(attachment_vals)
        self.document_attachment_id = attachment

        document = self._update_or_create_document_batch(attachment.id)
        document_url = '<a href="#" data-oe-model="%s" data-oe-id="%s">%s</a>' % (
            "documents.document", document.id, attachment.name
        )

        self.message_post(
            body=_("Certificados (ZIP) generados para el lote: %s") % (document_url),
            author_id=self.env.user.partner_id.id
        )
        return True
