
/* ---- Primo shared UI roles: the launcher and Settings (GTK4 only, scoped; nothing else is touched) ----
   A widget opts in with a role class. Colours are the named colours above; shape comes from the theme (rounding, menu_radius).
   Muted text is for the window background; on a card use the normal text colour (muted on a card is below 4.5:1 in a light theme).
   Error text is only safe at large sizes in every theme, so an error is shown with the normal text colour inside an error-coloured outline. */
window.primo-launcher .primo-popup, window.primo-settings .primo-popup { background-color: @window_bg_color; color: @window_fg_color; border: 1px solid alpha(@accent_bg_color, 0.55); border-radius: {{menu_radius}}px; }
window.primo-launcher .primo-surface, window.primo-settings .primo-surface { background-color: @card_bg_color; color: @card_fg_color; border-radius: {{menu_radius}}px; }
window.primo-launcher .primo-control, window.primo-settings .primo-control { border-radius: {{rounding}}px; }
window.primo-launcher .primo-title, window.primo-settings .primo-title { font-size: 17px; }
window.primo-launcher .primo-body, window.primo-settings .primo-body { font-size: 14px; }
window.primo-launcher .primo-caption, window.primo-settings .primo-caption { font-size: 11px; }
window.primo-launcher .primo-muted, window.primo-settings .primo-muted { color: #{{subtext}}; }
window.primo-launcher .primo-selected, window.primo-settings .primo-selected { background-color: alpha(@accent_bg_color, 0.30); color: @window_fg_color; }
window.primo-launcher .primo-control:focus-visible, window.primo-settings .primo-control:focus-visible,
window.primo-launcher .primo-selected:focus-visible, window.primo-settings .primo-selected:focus-visible { outline: 2px solid @accent_bg_color; outline-offset: -2px; }
window.primo-launcher .primo-control:disabled, window.primo-settings .primo-control:disabled,
window.primo-launcher .primo-disabled, window.primo-settings .primo-disabled { opacity: 0.45; }
window.primo-launcher .primo-error, window.primo-settings .primo-error { color: @window_fg_color; outline: 1px solid @error_color; outline-offset: -1px; }
window.primo-opaque .primo-selected { background-color: mix(@window_bg_color, @accent_bg_color, 0.3); }
window.primo-opaque .primo-popup { background-color: @window_bg_color; }
window.primo-opaque .primo-surface { background-color: @card_bg_color; }
window.primo-reduce-motion, window.primo-reduce-motion * { transition: none; animation: none; }
