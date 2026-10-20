/* The identity this build runs under: see cmake/modules/KritaAppIdentity.cmake */
#define KRITA_APP_SETTINGS_FOLDER "@KRITA_APP_SETTINGS_FOLDER@"
#define KRITA_APP_DISPLAY_NAME "@KRITA_APP_DISPLAY_NAME@"
#define KRITA_APP_ORGANIZATION_DOMAIN "@KRITA_APP_ORGANIZATION_DOMAIN@"
/* 1: Toska's splash screen (KisAppIdentity::hasOwnSplash()); 0: upstream's */
#define KRITA_APP_OWN_SPLASH @KRITA_APP_OWN_SPLASH@
/* 1: Toska's welcome page background (KisAppIdentity::hasOwnWelcome()); 0: upstream's plain welcome page */
#define KRITA_APP_OWN_WELCOME @KRITA_APP_OWN_WELCOME@
/* The colour theme the identity's shipped kritarc opens a new install with; empty: krita/data/kritarc's own ("Krita dark") */
#define KRITA_APP_DEFAULT_THEME "@KRITA_APP_DEFAULT_THEME@"
