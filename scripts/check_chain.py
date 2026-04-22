import importlib.util
import os

# Sesuaikan path ini dengan struktur repo kamu
VERSIONS_DIR = "alembic/versions"  # atau "migrations/versions"

chain = [
    ("001_create_users_v6", None),
    ("002_create_institutional_accounts", "001"),
    ("003_create_subscriptions", "002"),
    ("004_create_payment_transactions_v6", "003"),
    ("005_create_projects_v6", "004"),
    ("006_create_stage_runs_v6", "005"),
    ("009_create_stage_outputs_v6", "006"),
    ("010_create_institutional_seats", "009"),
    ("012_create_citation_style_mappings", "010"),
    ("013_no_op_saved_papers_deprecated", "012"),
    ("015_create_prompt_versions_v6", "013"),
    ("016_create_analytics_events_partitioned", "015"),
    ("017_create_feature_flags_v6", "016"),
    ("022_phase0_indexes_marker", "017"),
    ("023_add_triggers_updated_at", "022"),
    ("024_seed_initial_data_v6", "023"),
]

print("Verifikasi chain migration Fase 0 + Fase 1:")
all_ok = True
for name, expected_down in chain:
    filepath = os.path.join(VERSIONS_DIR, f"{name}.py")
    if not os.path.exists(filepath):
        print(f"  ✗ FILE NOT FOUND: {filepath}")
        all_ok = False
        continue
    spec = importlib.util.spec_from_file_location(name, filepath)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    got = getattr(mod, "down_revision", "MISSING")
    ok = got == expected_down
    status = "✓" if ok else f"✗ expected={expected_down!r}, got={got!r}"
    if not ok:
        all_ok = False
    revision = getattr(mod, "revision", "?")
    print(f"  {status} {name} (revision={revision})")

print()
print("✓ Semua chain valid" if all_ok else "✗ Ada chain yang rusak")
