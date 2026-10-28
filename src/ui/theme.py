"""Shared light theme for the operator workspace and its dialogs."""

import ttkbootstrap as tb
from ttkbootstrap.style import ThemeDefinition


PAGE = '#f1f4f8'
SURFACE = '#ffffff'
INK = '#1f3447'
MUTED = '#586a7e'
BORDER = '#dce6f2'
PRIMARY = '#339c6b'
PRIMARY_DARK = '#1f7f52'
BODY_FONT = 'Arial'
DISPLAY_FONT = 'Segoe UI'


def apply_theme(root):
    style = tb.Style()
    name = 'secondchecking'
    if name not in style.theme_names():
        style.register_theme(ThemeDefinition(name=name, themetype='light', colors={
            'primary': PRIMARY_DARK, 'secondary': '#6c757d', 'success': PRIMARY_DARK,
            'info': PRIMARY_DARK, 'warning': '#a16207', 'danger': '#dc3545',
            'light': '#f1f5f9', 'dark': INK, 'bg': PAGE, 'fg': INK,
            'selectbg': PRIMARY_DARK, 'selectfg': '#ffffff', 'border': BORDER,
            'inputfg': INK, 'inputbg': SURFACE, 'active': '#eaf4ef'}))
    if style.theme_use() != name:
        style.theme_use(name)
    root.configure(background=PAGE)
    if not getattr(root, '_workspace_fonts_set', False):
        root.option_add('*Font', (BODY_FONT, 10))
        root._workspace_fonts_set = True
    for label in ('Header', 'Surface'):
        style.configure(label + '.TFrame', background=SURFACE)
        style.configure(label + '.TLabel', background=SURFACE, foreground=INK)
    style.configure('HeaderTitle.TLabel', background=SURFACE, foreground=INK,
                    font=(DISPLAY_FONT, 16, 'bold'))
    style.configure('HeaderMuted.TLabel', background=SURFACE, foreground=MUTED,
                    font=(BODY_FONT, 9))
    style.configure('Muted.TLabel', foreground=MUTED, font=(BODY_FONT, 9))
    style.configure('TButton', padding=(14, 8))
    style.configure('TEntry', padding=(10, 8))
    style.configure('Treeview', font=(BODY_FONT, 10), borderwidth=0)
    style.configure('Treeview.Heading', font=(BODY_FONT, 10, 'bold'), padding=(10, 10))
    return style
