/** Where global setup leaves the signed-in sessions the specs run as. */
export const SHARED_STATE = "e2e/.auth/shared.json";

/** A clinic nothing writes to, so the empty screens can be seen. */
export const EMPTY_STATE = "e2e/.auth/empty.json";

/** A doctor at the shared clinic, signed in, with a profile linked to the account. */
export const DOCTOR_STATE = "e2e/.auth/doctor.json";

/** The profile that doctor's account is linked to, as the API described it. */
export const DOCTOR_PROFILE = "e2e/.auth/doctor-profile.json";

/** A platform administrator, made from the server's command line. */
export const PLATFORM_STATE = "e2e/.auth/platform.json";

/**
 * A clinic of its own for the platform to suspend. Its address is kept apart
 * from the accounts renewed before each test: if a run stopped with it still
 * suspended, renewing it would fail every test after.
 */
export const SPARE_CLINIC = "e2e/.auth/spare.json";

/** Whose sign-in each of the files above holds, so it can be renewed. */
export const ACCOUNTS = "e2e/.auth/accounts.json";

export const PASSWORD = "a properly long password";
