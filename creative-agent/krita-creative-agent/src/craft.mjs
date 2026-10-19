// @ts-check
// Native craft: whole areas through Krita's layers, selections, filters and colorize mask.
// The native_craft execution setting (default on) offers or hides all of them.
export const CRAFT_TOOLS = ['create_layer','set_layer','select','fill_region','apply_filter','colorize_flats','transform_layer','clone_layer','split_by_color','krita_action','composition_guides','krita_capabilities','make_material','stamp_material'];
// Craft tools that change the canvas; each name is also its bridge operation.
export const CRAFT_OPERATIONS = ['create_layer','set_layer','fill_region','apply_filter','colorize_flats','transform_layer','clone_layer','split_by_color','krita_action'];
// Operations that can run for minutes on a large canvas; past this the outcome is uncertain.
export const LONG_OPERATIONS = ['apply_filter','colorize_flats','split_by_color'];
// Comic page operations: comic_page is called by the host when painting starts; letter by the painter.
export const COMIC_OPERATIONS = ['comic_page','letter'];
