# B1-GOALS-01 Scope and Acceptance

## In scope

This Kanban run is scoped to the B-1 fluorescent-probe diagnostic benchmark for fire blight bacteria, specifically detection/diagnosis of Erwinia amylovora using the B-1 turn-on fluorescent probe. The run should use the Google Deep Research Max fixture on this topic and evaluate whether Muchanipo can produce an evidence-grounded research report for that fixture.

Anchor sources:

1. Jung Yuna et al. 2023. “On-site applicable diagnostic fluorescent probe for fire blight bacteria.” iScience. DOI: 10.1016/j.isci.2023.106557. PMCID: PMC10123346.
2. Jin Ji Hye et al. 2023. “Protocol for diagnosing Erwinia amylovora infection using a fluorescent probe.” STAR Protocols. DOI: 10.1016/j.xpro.2023.102412. PMCID: PMC10339246.

## Out of scope

The prior strawberry diagnostic-kit run is out of scope for benchmark comparison. Treat it only as an unrelated regression signal if it reveals app/runtime breakage; do not use its research content, scoring, or conclusions as evidence for this B-1 fixture.

## Evidence quality criteria

Acceptance requires visible, source-grounded evidence:

- Claims about the B-1 probe, fire blight bacteria, Erwinia amylovora diagnosis, protocol steps, specificity/selectivity, or field/on-site applicability must be traceable to cited sources.
- The two anchor papers above must be represented clearly and not replaced by unrelated plant-disease diagnostics.
- The report should distinguish primary-source findings from synthesis or app-generated reasoning.
- Evidence should include enough bibliographic detail for a user to verify the source: title, venue, year, DOI and/or PMCID where available.
- Strawberry-topic evidence must not appear as benchmark support for the B-1 fixture.

## App readiness criteria

The app is ready for this Kanban run when:

- The B-1 / Erwinia amylovora / fire-blight fixture can be launched without falling back to the strawberry topic.
- The run shows visible source collection, council/persona reasoning, report generation, and completion state.
- The generated report contains source citations and a claim/evidence structure sufficient to audit the main conclusions.
- The UI/runtime does not hide failures behind stale progress, stale report text, or unrelated fixture residue.
- Basic automated or manual checks confirm the run path completes and the final artifact is accessible to the user.

## Final user-test readiness definition

Ready for user test means a human can start the B-1 fixture from the app, watch it progress through source gathering and synthesis, and receive a final report that cites the two anchor papers and other relevant sources without strawberry contamination. The user-test pass condition is not “perfect science”; it is a coherent, inspectable, source-grounded B-1 fire-blight diagnostic report with clear completion status and no misleading fallback content.
