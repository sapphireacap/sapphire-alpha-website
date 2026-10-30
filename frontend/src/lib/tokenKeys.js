// Kept in its own module so anything that only needs the key (the router
// shell, the navbar's session check) does not pull the entire Auth page
// into the initial bundle just to read a string.
export const TRADER_TOKEN_KEY = "sac_trader_token";
