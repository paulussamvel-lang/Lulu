"""User-selectable workbench colors; independent from Qt and stored content."""
PALETTES = {
    'forest': dict(label='森林绿', canvas='#F2F5EF', surface='#FCFDF9', alt='#E6EEE3',
        ink='#293C33', muted='#566C5C', line='#CBD8C8', accent='#3D6B52', hover='#305640',
        rail='#2D493A', rail_active='#42614E', rail_text='#F4F9F3', rail_muted='#C0D4C5',
        selection='#85C59D', selection_ink='#10291B'),
    'sky': dict(label='浅蓝色', canvas='#EFF5FA', surface='#FBFDFF', alt='#E3EDF5',
        ink='#293C4E', muted='#536C81', line='#C7D7E4', accent='#386483', hover='#2A4F6B',
        rail='#304C64', rail_active='#45657E', rail_text='#F3F8FC', rail_muted='#C2D6E6',
        selection='#8DBFDF', selection_ink='#11283B'),
    'latte': dict(label='浅棕色', canvas='#F6F1EB', surface='#FFFCF8', alt='#ECE2D7',
        ink='#403329', muted='#76604F', line='#DCCDBF', accent='#7A5740', hover='#624330',
        rail='#59463A', rail_active='#765E4D', rail_text='#FFF9F0', rail_muted='#E2D0BE',
        selection='#D0AA8B', selection_ink='#302115'),
    'cream': dict(label='米黄色', canvas='#FAF6E9', surface='#FFFEF8', alt='#F0E9D3',
        ink='#3D392B', muted='#706547', line='#DCD2B6', accent='#74612B', hover='#5C4B1E',
        rail='#514A31', rail_active='#6C6342', rail_text='#FFFBEA', rail_muted='#DDD5B6',
        selection='#DFC575', selection_ink='#30270E'),
    'blush': dict(label='浅粉色', canvas='#FAF1F5', surface='#FFFBFD', alt='#F1E2EA',
        ink='#46313E', muted='#7A5C6D', line='#E2CAD7', accent='#885670', hover='#70435B',
        rail='#653F52', rail_active='#80566B', rail_text='#FFF5FA', rail_muted='#E7C9D8',
        selection='#DDA1BF', selection_ink='#32182A'),
}


def normalize_theme(name):
    return name if type(name) is str and name in {'warm', *PALETTES} else 'warm'


def theme_options():
    return tuple((name, values['label']) for name, values in PALETTES.items())
