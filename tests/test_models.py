# ═══════════════════════════════════════════════════════════════════════════
# File    : tests/test_models.py
# Desc    : Test suite untuk ORM models dan database constraints.
#           KOSONG di STEP 8 — test case diisi di Fase berikutnya.
#           File ini memastikan pytest discovery berjalan tanpa error.
#
#           Test yang akan ditambahkan (TODO Fase berikutnya):
#           - test_user_create: INSERT user, assert fields benar
#           - test_subscription_tier_constraint: tier harus 'free'|'sarjana'|...
#           - test_project_review_type_constraint: review_type harus 'narrative'|'systematic'
#           - test_stage_run_stage_type_constraint: stage_type harus P1–P8 values
#           - test_stage_output_one_to_one: satu stage_run → satu stage_output
#           - test_feature_flag_unique_name: duplicate name harus raise IntegrityError
#           - test_prompt_version_partial_unique: hanya satu is_active=True per (stage_type, prompt_name)
#
# Layer   : Tests / Models
# Step    : STEP 8 (skeleton) → Fase berikutnya (implementasi)
# Ref     : Blueprint §6.1–§6.15
# ═══════════════════════════════════════════════════════════════════════════
