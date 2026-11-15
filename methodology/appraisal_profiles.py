"""Explicit project rubrics and instrument guidance, not official instrument implementations."""

PROFILES = {
    "general": {
        "name": "Project-defined general study appraisal (not a validated instrument)",
        "guidance": "Select a design-specific instrument before making a formal risk-of-bias claim.",
        "domains": [
            (
                "design_fit",
                "Is the study design and comparator appropriate to the stated question?",
            ),
            (
                "selection",
                "Is sample selection described and representative of the target population?",
            ),
            ("measurement", "Are outcome measurements valid and consistently applied?"),
            (
                "confounding",
                "Are relevant confounding factors addressed by design or analysis?",
            ),
            (
                "missing_data",
                "Are missing data and exclusions reported and handled appropriately?",
            ),
            (
                "reporting",
                "Are prespecified outcomes and uncertainty estimates reported without selective reporting?",
            ),
        ],
    },
    "prediction": {
        "name": "Project-defined prediction-model appraisal (not the full PROBAST+AI instrument)",
        "guidance": "For formal prediction-model assessment use PROBAST+AI with its development/evaluation guidance: https://doi.org/10.1136/bmj-2024-082505",
        "domains": [
            (
                "participants",
                "Are participant selection, eligibility, data provenance and representativeness described?",
            ),
            (
                "predictors",
                "Are predictors available at the intended use time and measured without outcome leakage?",
            ),
            (
                "outcome",
                "Are outcome labels and reference standards defined and assessed independently of predictions?",
            ),
            (
                "analysis",
                "Are sample size, missing data, overfitting, tuning and performance uncertainty addressed?",
            ),
            (
                "validation",
                "Are training, tuning and test participants separated without patient overlap or data leakage, and is external validation reported?",
            ),
            (
                "applicability",
                "Does the evaluation population and setting match the intended clinical use, including relevant subgroups?",
            ),
        ],
    },
    "diagnostic": {
        "name": "Project-defined diagnostic-accuracy appraisal (not the full QUADAS instrument)",
        "guidance": "Diagnostic accuracy needs a tailored instrument and applicability judgements; historical QUADAS-2 guidance: https://www.bristol.ac.uk/population-health-sciences/projects/quadas/history/quadas-2/",
        "domains": [
            (
                "patient_selection",
                "Are patient sampling, exclusions and case-control selection appropriate for the target diagnostic population?",
            ),
            (
                "index_test",
                "Were index test thresholds prespecified and results interpreted independently of the reference standard?",
            ),
            (
                "reference_standard",
                "Is the reference standard credible and interpreted without knowledge of index test results?",
            ),
            (
                "flow_timing",
                "Are test timing, verification procedures, exclusions and inclusion of all participants in analysis appropriate?",
            ),
            (
                "applicability",
                "Do participants, index test and target condition match the review question?",
            ),
        ],
    },
}


def apply_profile(protocol, profile):
    from methodology.protocol import Domain

    rubric = PROFILES[profile]
    protocol.appraisal_name = rubric["name"]
    protocol.appraisal_domains = [
        Domain(id=k, question=q) for k, q in rubric["domains"]
    ]
    return protocol
