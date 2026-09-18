/** Where global setup leaves the signed-in sessions the specs run as. */
export const SHARED_STATE = "e2e/.auth/shared.json";

/** A clinic nothing writes to, so the empty screens can be seen. */
export const EMPTY_STATE = "e2e/.auth/empty.json";

/** A doctor at the shared clinic, signed in, with a profile linked to the account. */
export const DOCTOR_STATE = "e2e/.auth/doctor.json";

/** The profile that doctor's account is linked to, as the API described it. */
export const DOCTOR_PROFILE = "e2e/.auth/doctor-profile.json";
