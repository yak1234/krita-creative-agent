// @ts-check
// Native craft: whole areas through Krita's layers, selections, filters and colorize mask.
// The native_craft execution setting (default on) offers or hides all of them.
export const CRAFT_TOOLS = ['create_layer','set_layer','select','fill_region','apply_filter','colorize_flats','transform_layer','clone_layer','split_by_color','krita_action','composition_guides','krita_capabilities','make_material','stamp_material','bucket_fill','enclose_and_fill','krita_gradient','smart_patch'];
// Krita's own tools as functions: they need our Krita (the fork), which says so in its health check.
export const FORK_TOOLS = ['bucket_fill','enclose_and_fill','krita_gradient','smart_patch'];
// Craft tools that change the canvas; each name is also its bridge operation.
export const CRAFT_OPERATIONS = ['create_layer','set_layer','fill_region','apply_filter','colorize_flats','transform_layer','clone_layer','split_by_color','krita_action','bucket_fill','enclose_and_fill','krita_gradient','smart_patch'];
// Operations that can run for minutes on a large canvas; past this the outcome is uncertain. The finish (finish_pass.py)
// took about a minute on a whole 6000 x 4500 canvas offline.
// The full-size checks (area_compare.py) read a whole 6000 px canvas in squares: the long operations' time too.
export const LONG_OPERATIONS = ['apply_filter','colorize_flats','split_by_color','finish','area_likeness','area_accents','refine_map'];
// Comic page operations: comic_page is called by the host when painting starts; letter by the painter.
export const COMIC_OPERATIONS = ['comic_page','letter'];
