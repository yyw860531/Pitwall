# set_reference_lap.py
#
# Roadmap item — blocked on external reference lap support.
#
# Once the external reference lap feature is implemented (import a coach's
# driven lap or an AI ghost from another session), this script will:
#
#   python scripts/set_reference_lap.py <session_id> <lap_number>
#
#   1. Validate session_id and lap_number exist in the DB
#   2. Clear is_reference = 0 for all laps in the session
#   3. Set is_reference = 1 for the specified lap
#   4. Re-export dashboard.json so the UI reflects the change
#
# See roadmap: "External reference lap (coach's lap / AC AI ghost → .ld)"
