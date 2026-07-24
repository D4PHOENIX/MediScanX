BEGIN;

DROP PUBLICATION IF EXISTS powersync;
CREATE PUBLICATION powersync FOR TABLE doctor_profiles, patient_records, scan_results, chat_messages;

COMMIT;
