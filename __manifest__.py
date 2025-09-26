# -*- coding: utf-8 -*-
{
    'name': 'Sid NOI Cert Batch',
    'version': '1.0',
    'summary': 'Brief description of the module',
    'description': '''
        Detailed description of the module
    ''',
    'category': 'Uncategorized',
    'author': 'Suministros Industriales Diversos s.a.',
    'company': 'Suministros Industriales Diversos s.a.',
    'maintainer': 'Suministros Industriales Diversos s.a.',
    'depends': ['stock', 'stock_picking_batch','web' , 'documents', 'oct_certificate_receptions'],
    'data': [
        'views/sid_NOI_cert_batch_views.xml',
        "reports/report_notice_inspection_templates.xml",
        "reports/report_notice_inspection_action.xml",
    ],
    'license': 'LGPL-3',
    'installable': True,
    'application': False,
    'auto_install': False,
}