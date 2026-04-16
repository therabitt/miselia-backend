# ═════════════════════════════════════════════════════════════════════════════
# File    : scripts/seed_db.py
# Desc    : Seed initial data untuk Miselia — dipanggil oleh migration 024.
#           Berisi 3 fungsi idempotent:
#             - seed_prompt_versions()    : 22 prompt entries P1–P8
#             - seed_feature_flags()      : 19 feature flags
#             - seed_citation_style_mappings() : 31 program studi
#
#           Semua operasi menggunakan INSERT ... ON CONFLICT DO NOTHING
#           sehingga aman dijalankan ulang (idempotent).
#
#           Dipanggil dari: alembic/versions/024_seed_initial_data_v6.py
#           Bisa juga dijalankan standalone untuk re-seed:
#             python scripts/seed_db.py
#
# Layer   : Scripts / Seed
# Deps    : sqlalchemy (raw connection)
# Step    : STEP 6B — Seed Script
# Ref     : Blueprint §9.9 (prompt content), Appendix C (flags),
#           Appendix F (citation mappings)
# ═════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import sys
import os
import uuid
from datetime import datetime, timezone
from typing import Any

# Allow standalone execution
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ═════════════════════════════════════════════════════════════════════════════
# PART 1 — Prompt Versions Seed
# 22 entries, version=1, is_active=True
# Full content sesuai Blueprint §9.9
# Mapping: stage_type → prompt_name → konten prompt
# Ref: Blueprint §9.9, Appendix D migration 024
# ═════════════════════════════════════════════════════════════════════════════

PROMPT_VERSIONS_SEED: list[dict[str, Any]] = [

    # ── P1: Literature Review ─────────────────────────────────────────────

    {
        "stage_type": "literature_review",
        "prompt_name": "query_optimization",
        "version": 1,
        "content": (
            "Kamu adalah asisten penelitian akademik yang ahli dalam mencari literatur ilmiah.\n\n"
            "Topik penelitian: {topic}\n"
            "Bidang studi: {field_of_study}\n\n"
            "Tugasmu adalah menghasilkan 3–5 query pencarian yang berbeda namun saling melengkapi\n"
            "untuk menemukan paper akademik yang relevan dengan topik di atas.\n\n"
            "Aturan:\n"
            "1. Setiap query harus dalam Bahasa Inggris\n"
            "2. Variasikan pendekatan: broad query, specific query, methodological query\n"
            "3. Gunakan terminologi akademik yang tepat untuk bidang studi\n"
            "4. Jangan gunakan operator boolean\n"
            "5. Output HANYA array JSON, tidak ada teks lain\n\n"
            'Format output:\n["query 1", "query 2", "query 3", "query 4", "query 5"]'
        ),
    },

    {
        "stage_type": "literature_review",
        "prompt_name": "paper_relevance",
        "version": 1,
        "content": (
            "Kamu adalah reviewer jurnal akademik senior yang mengevaluasi relevansi paper\n"
            "terhadap topik penelitian.\n\n"
            "Topik penelitian: {topic}\n"
            "Bidang studi: {field_of_study}\n\n"
            "Untuk setiap paper di bawah ini, berikan:\n"
            "1. relevance_score: float 0.0–1.0\n"
            "2. relevance_reason: 1 kalimat mengapa paper ini relevan atau tidak\n"
            "3. key_findings: array 2–3 temuan utama (dari abstract)\n"
            "4. should_include: boolean\n\n"
            "Paper yang dievaluasi:\n"
            "{papers_json}\n\n"
            "Output HANYA JSON array, tidak ada teks lain:\n"
            '[{"paper_id": "...", "relevance_score": 0.85, "relevance_reason": "...",\n'
            '  "key_findings": ["..."], "should_include": true}]'
        ),
    },

    {
        "stage_type": "literature_review",
        "prompt_name": "landscape_overview",
        "version": 1,
        "content": (
            "Kamu adalah peneliti senior yang menulis tinjauan pustaka untuk jurnal akademik.\n\n"
            "Topik penelitian: {topic}\n"
            "Bidang studi: {field_of_study}\n\n"
            "Berdasarkan {paper_count} paper berikut, buatlah landscape overview:\n"
            "1. tema_utama: 3–5 tema besar yang muncul di literatur\n"
            "2. perkembangan_historis: narasi singkat perkembangan penelitian\n"
            "3. konsensus_penelitian: apa yang sudah disepakati mayoritas paper\n"
            "4. kontroversi_aktif: perdebatan yang masih berlangsung\n\n"
            "Paper:\n"
            "{selected_papers_json}\n\n"
            "Output HANYA JSON:\n"
            '{"tema_utama": [{"tema": "...", "paper_count": 3, "deskripsi": "..."}],\n'
            ' "perkembangan_historis": "...", "konsensus_penelitian": "...", "kontroversi_aktif": "..."}'
        ),
    },

    {
        "stage_type": "literature_review",
        "prompt_name": "lit_review_draft",
        "version": 1,
        "content": (
            "Kamu adalah penulis akademik senior yang menulis Bab Tinjauan Pustaka untuk skripsi/tesis.\n\n"
            "Topik penelitian: {topic}\n"
            "Bidang studi: {field_of_study}\n"
            "Format sitasi: {citation_style} (gunakan placeholder [AUTHOR_YEAR])\n\n"
            "Berdasarkan paper-paper berikut, tulis:\n"
            "1. lit_review_draft: Draft tinjauan pustaka dalam Bahasa Indonesia, minimal 800 kata\n"
            "2. research_gaps_basic: Array 3–5 research gap preview singkat\n\n"
            "Aturan:\n"
            "- Bahasa Indonesia akademik formal\n"
            "- Setiap paragraf minimal satu sitasi\n"
            "- Jangan copy-paste dari abstract — sintesis dan parafrase\n"
            "- Struktur: pembukaan → tema utama → perkembangan → implikasi\n\n"
            "Output HANYA JSON:\n"
            '{"lit_review_draft": "...", "research_gaps_basic": [{"gap": "...", "evidence": "..."}]}'
        ),
    },

    # ── P2: Research Gap & Novelty ────────────────────────────────────────

    {
        "stage_type": "research_gap",
        "prompt_name": "gap_identification",
        "version": 1,
        "content": (
            "Kamu adalah metodolog penelitian senior yang mengidentifikasi celah penelitian\n"
            "dari korpus literatur.\n\n"
            "Topik penelitian: {topic}\n"
            "Bidang studi: {field_of_study}\n\n"
            "Identifikasi 5–8 research gap yang nyata dan signifikan.\n"
            "Gap yang valid: empiris (belum diteliti), kontekstual (terbatas konteks),\n"
            "konsensus (hasil kontradiktif), teoritis (belum diuji)\n\n"
            "Untuk setiap gap:\n"
            '- gap_type: "empiris" | "kontekstual" | "konsensus" | "teoritis"\n'
            "- deskripsi: 2–3 kalimat\n"
            "- evidence: array paper_id\n"
            "- confidence: float 0.0–1.0\n\n"
            "Output HANYA JSON array:\n"
            '[{"gap_id": "gap_1", "gap_type": "...", "deskripsi": "...",\n'
            '  "evidence": ["paper_id_1"], "confidence": 0.78}]'
        ),
    },

    {
        "stage_type": "research_gap",
        "prompt_name": "novelty_synthesis",
        "version": 1,
        "content": (
            "Kamu adalah konsultan metodologi penelitian yang membantu mahasiswa merumuskan\n"
            "kebaruan penelitian.\n\n"
            "Topik: {topic}, Bidang studi: {field_of_study}\n\n"
            "Berdasarkan research gap berikut, buat:\n"
            "1. novelty_statements: Pernyataan kebaruan yang bisa langsung digunakan di Bab 1\n"
            "2. research_questions: Pertanyaan penelitian per gap\n\n"
            "Aturan:\n"
            "- Novelty statement harus spesifik terhadap gap\n"
            "- Bahasa Indonesia akademik\n"
            "- Research question harus measurable dan feasible\n\n"
            "Output HANYA JSON:\n"
            '{"novelty_statements": [{"gap_id": "gap_1", "statement": "...", "rationale": "..."}],\n'
            ' "research_questions": [{"gap_id": "gap_1", "question": "...",\n'
            '   "type": "deskriptif|komparatif|asosiatif|eksplanatif"}]}'
        ),
    },

    # ── P3: Methodology Advisor ───────────────────────────────────────────

    {
        "stage_type": "methodology_advisor",
        "prompt_name": "methodology_recommendation",
        "version": 1,
        "content": (
            "Kamu adalah konsultan metodologi penelitian yang merekomendasikan pendekatan\n"
            "penelitian berdasarkan gap dan constraints.\n\n"
            "Topik: {topic}, Bidang studi: {field_of_study}\n"
            "Gap yang dipilih: {selected_gap}\n\n"
            "Constraints:\n"
            "- Estimasi sampel: {sample_size_range}\n"
            "- Sisa waktu: {time_remaining}\n\n"
            "Evaluasi kelayakan tiga pendekatan: kuantitatif, kualitatif, mixed methods.\n"
            "Untuk setiap pendekatan berikan: approach_name, feasibility_score (0–1),\n"
            "alasan_rekomendasi, alasan_ketidakcocokan (jika tidak cocok)\n\n"
            "Output HANYA JSON:\n"
            '{"recommended_approach": "kuantitatif|kualitatif|mixed",\n'
            ' "recommendation_confidence": 0.85,\n'
            ' "reasoning": "...",\n'
            ' "approaches": [{"approach": "...", "feasibility_score": 0.9,\n'
            '                 "alasan": "...", "catatan": "..."}]}'
        ),
    },

    {
        "stage_type": "methodology_advisor",
        "prompt_name": "instrument_analysis",
        "version": 1,
        "content": (
            "Kamu adalah metodolog yang merekomendasikan instrumen dan teknik analisis\n"
            "untuk pendekatan penelitian yang sudah dipilih.\n\n"
            "Topik: {topic}, Bidang studi: {field_of_study}\n"
            "Pendekatan: {recommended_approach}\n"
            "Gap yang diteliti: {selected_gap}\n\n"
            "Rekomendasikan:\n"
            "1. instruments[]: instrumen pengumpulan data dengan nama dan referensi validasi jika ada\n"
            "2. analysis_techniques[]: teknik analisis yang sesuai\n"
            "3. software_recommendations[]: software yang direkomendasikan\n\n"
            "Output HANYA JSON:\n"
            '{"instruments": [{"name": "...", "type": "...", "validation_reference": "..."}],\n'
            ' "analysis_techniques": [{"name": "...", "description": "...", "when_to_use": "..."}],\n'
            ' "software_recommendations": [{"name": "SPSS|SmartPLS|NVivo|Atlas.ti",\n'
            '                                "reason": "..."}]}'
        ),
    },

    # ── P4: Hypothesis & Variable (Kuantitatif) ───────────────────────────

    {
        "stage_type": "hypothesis_variable",
        "prompt_name": "variable_identification",
        "version": 1,
        "content": (
            "Kamu adalah metodolog yang membantu mengidentifikasi variabel penelitian\n"
            "untuk penelitian kuantitatif.\n\n"
            "Topik: {topic}, Bidang studi: {field_of_study}\n"
            "Research gap: {selected_gap}\n"
            "Research question: {research_question}\n\n"
            "Identifikasi:\n"
            "1. variables[]: variabel independen, dependen, dan moderating/mediating (jika relevan)\n"
            "2. Untuk setiap variabel: operasionalisasi dengan 3–5 indikator yang terukur\n\n"
            "Output HANYA JSON:\n"
            '{"variables": [{"name": "...", "role": "independen|dependen|moderating|mediating",\n'
            '                "definition": "...",\n'
            '                "indicators": ["indikator 1", "indikator 2", "indikator 3"]}]}'
        ),
    },

    {
        "stage_type": "hypothesis_variable",
        "prompt_name": "hypothesis_generation",
        "version": 1,
        "content": (
            "Kamu adalah metodolog yang membantu merumuskan hipotesis penelitian.\n\n"
            "Variabel: {variables_json}\n"
            "Research gap: {selected_gap}\n\n"
            "Rumuskan hipotesis penelitian:\n"
            "1. H1, H2, ... (hipotesis alternatif per hubungan variabel)\n"
            "2. H0 untuk setiap hipotesis alternatif\n\n"
            "Bahasa Indonesia akademik. Setiap hipotesis harus operasional dan testable.\n\n"
            "Output HANYA JSON:\n"
            '{"hypotheses": [{"id": "H1", "statement": "...", "type": "alternatif",\n'
            '                 "paired_with": "H0_1"},\n'
            '                {"id": "H0_1", "statement": "...", "type": "null"}]}'
        ),
    },

    # ── P4: Proposisi & Tema (Kualitatif) ─────────────────────────────────

    {
        "stage_type": "proposisi_tema",
        "prompt_name": "theme_mapping",
        "version": 1,
        "content": (
            "Kamu adalah peneliti kualitatif senior yang memetakan tema eksplorasi.\n\n"
            "Topik: {topic}, Bidang studi: {field_of_study}\n"
            "Research gap: {selected_gap}, Pendekatan: {qualitative_approach}\n\n"
            "Petakan tema-tema yang akan dieksplorasi:\n"
            "1. themes[]: tema utama (3–5 tema) dengan sub-tema per tema\n"
            "2. Setiap tema harus spesifik terhadap gap yang dipilih\n\n"
            "Output HANYA JSON:\n"
            '{"themes": [{"theme": "...", "description": "...",\n'
            '             "sub_themes": ["sub-tema 1", "sub-tema 2"]}]}'
        ),
    },

    {
        "stage_type": "proposisi_tema",
        "prompt_name": "proposition_generation",
        "version": 1,
        "content": (
            "Tema penelitian: {themes_json}\n"
            "Research gap: {selected_gap}\n\n"
            "Rumuskan:\n"
            "1. propositions[]: proposisi penelitian per tema (bukan hipotesis)\n"
            "2. guiding_questions[]: pertanyaan panduan per tema untuk wawancara/observasi\n\n"
            "Output HANYA JSON:\n"
            '{"propositions": [{"theme": "...", "proposition": "..."}],\n'
            ' "guiding_questions": [{"theme": "...", "questions": ["pertanyaan 1", "pertanyaan 2"]}]}'
        ),
    },

    # ── P5: Chapter Outline ───────────────────────────────────────────────

    {
        "stage_type": "chapter_outline",
        "prompt_name": "chapter_outline",
        "version": 1,
        "content": (
            "Kamu adalah konsultan akademik yang membantu menyusun outline skripsi/tesis.\n\n"
            "Jenjang: {education_level}, Bidang studi: {field_of_study}\n"
            "Data yang tersedia dari pipeline sebelumnya:\n"
            "{available_outputs_summary}\n\n"
            "Susun outline lengkap skripsi dengan sub-bab per bab.\n"
            "Sesuaikan dengan standar umum skripsi Indonesia untuk jenjang tersebut.\n"
            "Sertakan estimasi panjang per bab (dalam halaman).\n\n"
            "Output HANYA JSON:\n"
            '{"chapters": [{"chapter_number": 1, "title": "PENDAHULUAN",\n'
            '               "sub_chapters": [{"number": "1.1", "title": "Latar Belakang",\n'
            '                                  "notes": "poin-poin yang harus ada"}],\n'
            '               "estimated_pages": {"min": 15, "max": 20}}],\n'
            ' "total_estimated_pages": {"min": 70, "max": 100}}'
        ),
    },

    # ── P6: Bab 1 Writer ──────────────────────────────────────────────────

    {
        "stage_type": "bab1_writer",
        "prompt_name": "latar_belakang",
        "version": 1,
        "content": (
            "Kamu adalah penulis akademik yang membantu menulis Bab 1 skripsi/tesis.\n\n"
            "Topik: {topic}, Bidang studi: {field_of_study}\n"
            "Landscape overview: {landscape_overview}\n"
            "Research gap yang dipilih: {selected_gap}\n\n"
            "Tulis latar belakang masalah dalam Bahasa Indonesia akademik (3–5 paragraf).\n"
            "Gunakan placeholder [AUTHOR_YEAR] untuk sitasi.\n"
            "Alur: konteks umum → penyempitan → identifikasi masalah → urgensi penelitian\n\n"
            "Output HANYA JSON:\n"
            '{"latar_belakang": "..."}'
        ),
    },

    {
        "stage_type": "bab1_writer",
        "prompt_name": "identifikasi_rumusan_masalah",
        "version": 1,
        "content": (
            "Latar belakang: {latar_belakang}\n"
            "Research gaps: {validated_gaps}\n\n"
            "Rumuskan:\n"
            "1. identifikasi_masalah[]: daftar masalah yang teridentifikasi (numbered)\n"
            "2. rumusan_masalah[]: pertanyaan penelitian formal (kalimat tanya akademik)\n\n"
            "Output HANYA JSON:\n"
            '{"identifikasi_masalah": ["Masalah 1: ...", "Masalah 2: ..."],\n'
            ' "rumusan_masalah": ["Bagaimana...", "Apakah..."]}'
        ),
    },

    {
        "stage_type": "bab1_writer",
        "prompt_name": "tujuan_manfaat",
        "version": 1,
        "content": (
            "Rumusan masalah: {rumusan_masalah}\n\n"
            "Rumuskan tujuan dan manfaat penelitian yang sesuai dengan rumusan masalah.\n\n"
            "Output HANYA JSON:\n"
            '{"tujuan_penelitian": ["Untuk mengetahui...", "Untuk menganalisis..."],\n'
            ' "manfaat_penelitian": {"teoritis": ["..."], "praktis": ["..."]}}'
        ),
    },

    # ── P7: Systematic Literature Review (Magister only) ─────────────────

    {
        "stage_type": "systematic_review",
        "prompt_name": "pico_criteria",
        "version": 1,
        "content": (
            "Kamu adalah metodolog systematic review senior.\n\n"
            "Topik: {topic}, Bidang studi: {field_of_study}\n"
            "PICO: Population={population}, Interest={interest},\n"
            "      Comparison={comparison}, Outcome={outcome}\n\n"
            "Generate:\n"
            "1. inclusion_criteria[]: kriteria inklusi berdasarkan PICO\n"
            "2. exclusion_criteria[]: kriteria eksklusi yang jelas dan operasional\n\n"
            "Output HANYA JSON:\n"
            '{"inclusion_criteria": ["Studi yang...", "Paper dari tahun..."],\n'
            ' "exclusion_criteria": ["Studi yang tidak...", "Paper yang..."]}'
        ),
    },

    {
        "stage_type": "systematic_review",
        "prompt_name": "prisma_screening",
        "version": 1,
        "content": (
            "Kriteria inklusi: {inclusion_criteria}\n"
            "Kriteria eksklusi: {exclusion_criteria}\n\n"
            "Untuk setiap paper, tentukan apakah lolos title/abstract screening.\n\n"
            "Output HANYA JSON array:\n"
            '[{"paper_id": "...", "passes_screening": true,\n'
            '  "screening_reason": "..."}]'
        ),
    },

    {
        "stage_type": "systematic_review",
        "prompt_name": "quality_assessment",
        "version": 1,
        "content": (
            "Kamu adalah metodolog yang melakukan penilaian kualitas studi.\n"
            "Gunakan JBI Critical Appraisal Tools.\n\n"
            "Untuk setiap paper, berikan quality score (0–1) dan justifikasi.\n\n"
            "Output HANYA JSON array:\n"
            '[{"paper_id": "...", "quality_score": 0.82,\n'
            '  "quality_justification": "...", "risk_of_bias": "low|medium|high"}]'
        ),
    },

    {
        "stage_type": "systematic_review",
        "prompt_name": "evidence_synthesis",
        "version": 1,
        "content": (
            "Kamu adalah peneliti senior yang mensintesis bukti dari systematic review.\n\n"
            "Berdasarkan paper-paper yang lolos quality assessment, buat:\n"
            "1. thematic_synthesis: sintesis tematik (serupa landscape overview tapi lebih ketat)\n"
            "2. evidence_table: matriks paper × temuan kunci × quality score\n\n"
            "Output HANYA JSON:\n"
            '{"thematic_synthesis": {"tema_utama": [...], "konsensus": "...", "gaps": "..."},\n'
            ' "evidence_table": [{"paper_id": "...", "key_findings": ["..."], "quality_score": 0.82}]}'
        ),
    },

    # ── P8: Sidang Preparation ────────────────────────────────────────────

    {
        "stage_type": "sidang_preparation",
        "prompt_name": "weakness_identification",
        "version": 1,
        "content": (
            "Kamu adalah penguji sidang skripsi senior yang mengidentifikasi kelemahan penelitian.\n\n"
            "Analisis seluruh output penelitian berikut dan identifikasi kelemahan yang paling\n"
            "mungkin ditanyakan oleh penguji:\n\n"
            "{all_project_outputs_summary}\n\n"
            "Output HANYA JSON:\n"
            '{"weaknesses": [{"category": "metodologi|novelty|data|implikasi|lainnya",\n'
            '                 "description": "...", "severity": "tinggi|sedang|rendah"}]}'
        ),
    },

    {
        "stage_type": "sidang_preparation",
        "prompt_name": "question_answer_generation",
        "version": 1,
        "content": (
            "Weaknesses: {weaknesses}\n"
            "Project summary: {project_summary}\n"
            "Bidang studi: {field_of_study}\n\n"
            "Generate prediksi pertanyaan sidang dengan jawaban yang disarankan.\n"
            "Kategorikan: SANGAT MUNGKIN / MUNGKIN / BISA JADI\n\n"
            "Output HANYA JSON:\n"
            '{"predicted_questions": [{"question": "...", "category": "SANGAT MUNGKIN",\n'
            '                          "suggested_answer_points": ["poin 1", "poin 2", "poin 3"],\n'
            '                          "related_weakness_id": "..."}]}'
        ),
    },
]


# ═════════════════════════════════════════════════════════════════════════════
# PART 2 — Feature Flags Seed
# 19 flags — Blueprint Appendix C (source of truth)
# Ref: Appendix C, konflik 20/21 di PMD/Appendix D sudah di-resolve
# ═════════════════════════════════════════════════════════════════════════════

FEATURE_FLAGS_SEED: list[dict[str, Any]] = [
    # Pipeline availability — MVP (aktif di launch)
    {"name": "pipeline_1_enabled",          "is_enabled": True,  "description": "P1: Literature Review"},
    {"name": "pipeline_2_enabled",          "is_enabled": True,  "description": "P2: Research Gap"},
    # Pipeline availability — Tier A (aktif Bulan 2)
    {"name": "pipeline_3_enabled",          "is_enabled": False, "description": "P3: Methodology Advisor (Tier A)"},
    {"name": "pipeline_4_enabled",          "is_enabled": False, "description": "P4: Hypothesis/Proposisi (Tier A)"},
    {"name": "pipeline_5_enabled",          "is_enabled": False, "description": "P5: Chapter Outline (Tier A)"},
    # Pipeline availability — Tier B (aktif Bulan 4+)
    {"name": "pipeline_6_enabled",          "is_enabled": False, "description": "P6: Bab 1 Writer (Tier B)"},
    {"name": "pipeline_7_enabled",          "is_enabled": False, "description": "P7: SLR Magister only (Tier B)"},
    {"name": "pipeline_8_enabled",          "is_enabled": False, "description": "P8: Sidang Preparation (Tier B)"},
    # Core features (aktif di launch)
    {"name": "find_papers_enabled",         "is_enabled": True,  "description": "Find Papers workflow"},
    {"name": "library_enabled",             "is_enabled": True,  "description": "Library feature"},
    {"name": "chat_with_papers_enabled",    "is_enabled": True,  "description": "Chat with Papers"},
    # Tier A features
    {"name": "csv_import_enabled",          "is_enabled": False, "description": "CSV import ke Library — aktif akhir Fase 5 (Decision #28)"},
    {"name": "bib_ris_import_enabled",      "is_enabled": False, "description": "BibTeX & RIS import ke Library — aktif Tier A (Decision #28)"},
    {"name": "referral_system_enabled",     "is_enabled": False, "description": "Referral system (Tier A)"},
    {"name": "institutional_plan_enabled",  "is_enabled": False, "description": "Institutional plan (Tier A)"},
    # Tier B features
    {"name": "auto_debit_enabled",          "is_enabled": False, "description": "Auto-debit renewal (Tier B)"},
    {"name": "websocket_progress_enabled",  "is_enabled": False, "description": "WebSocket progress (Tier B)"},
    {"name": "collaboration_enabled",       "is_enabled": False, "description": "Project sharing (Tier B)"},
    # AI Infrastructure
    {"name": "ai_fallback_enabled",         "is_enabled": True,  "description": "AI fallback ke Claude/Gemini jika GPT-4o down (Decision #23)"},
]


# ═════════════════════════════════════════════════════════════════════════════
# PART 3 — Citation Style Mappings Seed
# 31 program studi — Blueprint Appendix F
# High (18) + Medium (12) + Low (1) = 31
# ═════════════════════════════════════════════════════════════════════════════

CITATION_STYLE_MAPPINGS_SEED: list[dict[str, Any]] = [
    # ── HIGH confidence (18) ──────────────────────────────────────────────
    {"field_of_study": "Psikologi",               "recommended_style": "apa7",      "confidence_level": "high",   "notes": None},
    {"field_of_study": "Ilmu Pendidikan",          "recommended_style": "apa7",      "confidence_level": "high",   "notes": None},
    {"field_of_study": "Bimbingan dan Konseling",  "recommended_style": "apa7",      "confidence_level": "high",   "notes": None},
    {"field_of_study": "Sosiologi",                "recommended_style": "apa7",      "confidence_level": "high",   "notes": None},
    {"field_of_study": "Ilmu Komunikasi",          "recommended_style": "apa7",      "confidence_level": "high",   "notes": None},
    {"field_of_study": "Kesehatan Masyarakat",     "recommended_style": "vancouver", "confidence_level": "high",   "notes": None},
    {"field_of_study": "Kedokteran",               "recommended_style": "vancouver", "confidence_level": "high",   "notes": None},
    {"field_of_study": "Keperawatan",              "recommended_style": "vancouver", "confidence_level": "high",   "notes": None},
    {"field_of_study": "Farmasi",                  "recommended_style": "vancouver", "confidence_level": "high",   "notes": None},
    {"field_of_study": "Teknik Elektro",           "recommended_style": "ieee",      "confidence_level": "high",   "notes": None},
    {"field_of_study": "Teknik Informatika",       "recommended_style": "ieee",      "confidence_level": "high",   "notes": None},
    {"field_of_study": "Ilmu Komputer",            "recommended_style": "ieee",      "confidence_level": "high",   "notes": None},
    {"field_of_study": "Teknik Sipil",             "recommended_style": "ieee",      "confidence_level": "high",   "notes": None},
    {"field_of_study": "Teknik Mesin",             "recommended_style": "ieee",      "confidence_level": "high",   "notes": None},
    {"field_of_study": "Matematika",               "recommended_style": "ieee",      "confidence_level": "high",   "notes": None},
    {"field_of_study": "Fisika",                   "recommended_style": "ieee",      "confidence_level": "high",   "notes": None},
    {"field_of_study": "Sastra Indonesia",         "recommended_style": "mla9",      "confidence_level": "high",   "notes": None},
    {"field_of_study": "Sastra Inggris",           "recommended_style": "mla9",      "confidence_level": "high",   "notes": None},
    # ── MEDIUM confidence (12) ────────────────────────────────────────────
    {"field_of_study": "Manajemen",                "recommended_style": "apa7",      "confidence_level": "medium", "notes": "Beberapa institusi menggunakan Chicago"},
    {"field_of_study": "Akuntansi",                "recommended_style": "apa7",      "confidence_level": "medium", "notes": None},
    {"field_of_study": "Ekonomi",                  "recommended_style": "apa7",      "confidence_level": "medium", "notes": "Economics journals sering IEEE atau Chicago"},
    {"field_of_study": "Hukum",                    "recommended_style": "chicago",   "confidence_level": "medium", "notes": "Bervariasi antar fakultas hukum"},
    {"field_of_study": "Sejarah",                  "recommended_style": "chicago",   "confidence_level": "medium", "notes": None},
    {"field_of_study": "Ilmu Politik",             "recommended_style": "apa7",      "confidence_level": "medium", "notes": None},
    {"field_of_study": "Hubungan Internasional",   "recommended_style": "apa7",      "confidence_level": "medium", "notes": None},
    {"field_of_study": "Administrasi Publik",      "recommended_style": "apa7",      "confidence_level": "medium", "notes": None},
    {"field_of_study": "Antropologi",              "recommended_style": "apa7",      "confidence_level": "medium", "notes": None},
    {"field_of_study": "Biologi",                  "recommended_style": "vancouver", "confidence_level": "medium", "notes": None},
    {"field_of_study": "Kimia",                    "recommended_style": "vancouver", "confidence_level": "medium", "notes": None},
    {"field_of_study": "Gizi dan Dietetika",       "recommended_style": "vancouver", "confidence_level": "medium", "notes": None},
    # ── LOW confidence (1) ────────────────────────────────────────────────
    {"field_of_study": "Arsitektur",               "recommended_style": "apa7",      "confidence_level": "low",    "notes": "Sangat bervariasi per institusi"},
]


# ═════════════════════════════════════════════════════════════════════════════
# Seed functions — dipanggil dari migration 024 atau standalone
# ═════════════════════════════════════════════════════════════════════════════

def seed_prompt_versions(bind: Any) -> None:
    """
    Seed 22 prompt entries ke tabel prompt_versions.
    Idempotent: skip jika (stage_type, prompt_name, version) sudah ada.
    Ref: Blueprint §9.9, Appendix D migration 024
    """
    now = datetime.now(timezone.utc)
    inserted = 0
    skipped = 0

    for entry in PROMPT_VERSIONS_SEED:
        # Cek apakah sudah ada (idempotency check)
        result = bind.execute(
            __import__("sqlalchemy").text(
                "SELECT id FROM prompt_versions "
                "WHERE stage_type = :stage_type "
                "AND prompt_name = :prompt_name "
                "AND version = :version"
            ),
            {
                "stage_type": entry["stage_type"],
                "prompt_name": entry["prompt_name"],
                "version": entry["version"],
            },
        ).fetchone()

        if result is not None:
            skipped += 1
            continue

        bind.execute(
            __import__("sqlalchemy").text(
                "INSERT INTO prompt_versions "
                "(id, stage_type, prompt_name, version, content, is_active, created_at) "
                "VALUES (:id, :stage_type, :prompt_name, :version, :content, :is_active, :created_at)"
            ),
            {
                "id": str(uuid.uuid4()),
                "stage_type": entry["stage_type"],
                "prompt_name": entry["prompt_name"],
                "version": entry["version"],
                "content": entry["content"],
                "is_active": True,
                "created_at": now,
            },
        )
        inserted += 1

    print(f"  seed_prompt_versions: {inserted} inserted, {skipped} skipped")
    assert (inserted + skipped) == 22, (
        f"Expected 22 prompt entries total, got {inserted + skipped}"
    )


def seed_feature_flags(bind: Any) -> None:
    """
    Seed 19 feature flags ke tabel feature_flags.
    Idempotent: skip jika name sudah ada.
    Ref: Blueprint Appendix C (source of truth — bukan 20/21 dari PMD/Appendix D)
    """
    now = datetime.now(timezone.utc)
    inserted = 0
    skipped = 0

    for flag in FEATURE_FLAGS_SEED:
        result = bind.execute(
            __import__("sqlalchemy").text(
                "SELECT id FROM feature_flags WHERE name = :name"
            ),
            {"name": flag["name"]},
        ).fetchone()

        if result is not None:
            skipped += 1
            continue

        bind.execute(
            __import__("sqlalchemy").text(
                "INSERT INTO feature_flags "
                "(id, name, is_enabled, description, created_at, updated_at) "
                "VALUES (:id, :name, :is_enabled, :description, :created_at, :updated_at)"
            ),
            {
                "id": str(uuid.uuid4()),
                "name": flag["name"],
                "is_enabled": flag["is_enabled"],
                "description": flag["description"],
                "created_at": now,
                "updated_at": now,
            },
        )
        inserted += 1

    print(f"  seed_feature_flags: {inserted} inserted, {skipped} skipped")
    assert (inserted + skipped) == 19, (
        f"Expected 19 feature flags total, got {inserted + skipped}"
    )


def seed_citation_style_mappings(bind: Any) -> None:
    """
    Seed 31 citation style mappings ke tabel citation_style_mappings.
    Idempotent: skip jika field_of_study sudah ada.
    Ref: Blueprint Appendix F
    Distribution: HIGH=18, MEDIUM=12, LOW=1
    """
    now = datetime.now(timezone.utc)
    inserted = 0
    skipped = 0

    for mapping in CITATION_STYLE_MAPPINGS_SEED:
        result = bind.execute(
            __import__("sqlalchemy").text(
                "SELECT id FROM citation_style_mappings WHERE field_of_study = :field_of_study"
            ),
            {"field_of_study": mapping["field_of_study"]},
        ).fetchone()

        if result is not None:
            skipped += 1
            continue

        bind.execute(
            __import__("sqlalchemy").text(
                "INSERT INTO citation_style_mappings "
                "(id, field_of_study, recommended_style, confidence_level, notes, created_at) "
                "VALUES (:id, :field_of_study, :recommended_style, :confidence_level, :notes, :created_at)"
            ),
            {
                "id": str(uuid.uuid4()),
                "field_of_study": mapping["field_of_study"],
                "recommended_style": mapping["recommended_style"],
                "confidence_level": mapping["confidence_level"],
                "notes": mapping["notes"],
                "created_at": now,
            },
        )
        inserted += 1

    print(f"  seed_citation_style_mappings: {inserted} inserted, {skipped} skipped")
    assert (inserted + skipped) == 31, (
        f"Expected 31 citation mappings total, got {inserted + skipped}"
    )


# ═════════════════════════════════════════════════════════════════════════════
# Standalone execution — untuk re-seed manual tanpa alembic
# ═════════════════════════════════════════════════════════════════════════════

def _run_standalone() -> None:
    """
    Jalankan seed secara standalone:
      python scripts/seed_db.py
    Membutuhkan DATABASE_URL di .env atau environment.
    """
    from sqlalchemy import create_engine, text
    from app.config import settings

    print("Running seed_db.py standalone...")
    print(f"  Target DB: {settings.DATABASE_URL[:40]}...")

    # Gunakan sync engine untuk standalone (bukan async)
    sync_url = settings.DATABASE_URL
    if sync_url.startswith("postgresql+asyncpg://"):
        sync_url = sync_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    if sync_url.startswith("postgres://"):
        sync_url = sync_url.replace("postgres://", "postgresql://", 1)

    engine = create_engine(sync_url)
    with engine.begin() as conn:
        print("\nSeeding prompt_versions...")
        seed_prompt_versions(conn)

        print("Seeding feature_flags...")
        seed_feature_flags(conn)

        print("Seeding citation_style_mappings...")
        seed_citation_style_mappings(conn)

    print("\n✓ Seed selesai.")


if __name__ == "__main__":
    _run_standalone()
