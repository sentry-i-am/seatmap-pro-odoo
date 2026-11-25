{
    'name': 'Seatmap Pro Seating for Events',
    'version': '19.0.0.1.0',
    'category': 'Marketing/Events',
    'summary': 'Buyers pick seats on a Seatmap Pro venue map when they register on the website',
    'author': 'Seatmap Pro',
    'website': 'https://seatmap.pro',
    'license': 'Other OSI approved licence',
    'depends': ['website_event_sale'],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_cron.xml',
        'views/res_config_settings_views.xml',
        'views/event_event_views.xml',
        'views/event_registration_views.xml',
        'views/website_templates.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'seatmap_pro_event/static/src/interactions/seat_picker.js',
            'seatmap_pro_event/static/src/scss/seat_picker.scss',
        ],
    },
    'installable': True,
}
