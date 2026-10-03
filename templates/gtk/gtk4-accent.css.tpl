
/* ---- GTK4 built-in theme hard-codes its blue; recolour every accent usage ---------------
   (apps built on libadwaita read the named colours above and do not need this.) */
progressbar > trough > progress, scale > trough > highlight { border-color: @accent_bg_color; background-color: @accent_bg_color; }
levelbar > trough > block.high, levelbar > trough > block:not(.empty) { border-color: @accent_bg_color; background-color: @accent_bg_color; }
row:selected progressbar > trough > progress, row:selected scale > trough > highlight { border-color: @accent_fg_color; }
columnview.view.progressbar, treeview.view.progressbar { background-color: @accent_bg_color; background-image: image(@accent_bg_color); }

switch:checked { color: @accent_fg_color; border-color: transparent; background-color: @accent_bg_color; }
check:checked, radio:checked, check:indeterminate, radio:indeterminate {
    background-image: none; background-color: @accent_bg_color; border-color: @accent_bg_color; color: @accent_fg_color;
}

button.suggested-action { color: @accent_fg_color; border-color: transparent; background-image: none; background-color: @accent_bg_color; outline-color: rgba({{base_rgb}}, 0.3); }
button.suggested-action.flat { background-color: transparent; color: @accent_color; }
button.link, link, button.link:active, link:active { color: @accent_color; }
menubar > item:selected { box-shadow: inset 0 -3px @accent_bg_color; color: @accent_color; }
paned > separator:selected { background-image: image(@accent_bg_color); }
placessidebar .navigation-sidebar > row.sidebar-new-bookmark-row { color: @accent_color; }

notebook > header.top > tabs > tab:checked { box-shadow: inset 0 -3px @accent_bg_color; }
notebook > header.bottom > tabs > tab:checked { box-shadow: inset 0 3px @accent_bg_color; }
notebook > header.left > tabs > tab:checked { box-shadow: inset -3px 0 @accent_bg_color; }
notebook > header.right > tabs > tab:checked { box-shadow: inset 3px 0 @accent_bg_color; }

.view:selected:focus, .view:selected, textview > text:selected:focus, textview > text:selected, iconview:selected:focus, iconview:selected,
flowbox > flowboxchild:selected, gridview > child:selected, modelbutton.flat:selected, columnview.view:selected:focus, columnview.view:selected,
treeview.view:selected:focus, treeview.view:selected, row:selected, calendar > grid > label.day-number:selected,
.content-view .tile:active, .content-view .tile:selected { background-color: @accent_bg_color; color: @accent_fg_color; }
textview > text > selection:focus-within { background-color: rgba({{accent_rgb}}, 0.45); }
calendar > grid > label.day-number:checked { background-color: rgba({{accent_rgb}}, 0.3); }
filechooser gridview child:selected { background-color: rgba({{accent_rgb}}, 0.18); color: inherit; }
filechooser gridview child:selected:hover { background-color: rgba({{accent_rgb}}, 0.26); }
filechooser gridview child:selected:active { background-color: rgba({{accent_rgb}}, 0.32); }
popover.emoji-picker emoji:focus, popover.emoji-picker emoji:hover { background: @accent_bg_color; }

iconview:focus:focus-visible, flowbox > flowboxchild:focus:focus-visible, gridview > child:focus:focus-visible, label:focus:focus-visible,
notebook > header > tabs > arrow:focus:focus-visible, button:focus:focus-visible { outline-color: rgba({{accent_rgb}}, 0.7); }
