# Optimizing LLM query understanding: a ShopAssist learning guide

Date: 2026-10-09. This guide distinguishes semantic correctness, representational capacity, validation and operational reliability. ShopAssist production still uses v1; v2 and new prompts/rules are experimental. Larger live comparisons were deferred. References R1–R12 resolve to titled primary sources with dates and URLs in the [research review](../phase8_2/research_review.md); repository examples and measurements resolve to the [results](../phase8_2/experimental_results.md) and [contract review](../phase8_2/query_contract_review.md).

## 1. Query understanding

**Definition:** translating a user's request into a representation that downstream software can consume. **Intuition:** separate what the user wants from how they phrase it. **Technical detail:** a function f(query) produces item identity, constraints, preferences, exclusions and clarification state. Correctness requires preserving intent across that transformation. **ShopAssist:** lightweight Nike shoes under2000 needs Footwear, Nike, a strict budget and lightweight preference. **Trade-off:** a short schema is cheap but may omit alternatives or negation scope. **References:** R1/R3 and the contract review.

## 2. Information extraction

**Definition:** identifying relevant entities and relationships in text. **Intuition:** highlight useful facts without turning every noun into a filter. **Technical detail:** extraction is separate from catalog eligibility: a manufacturer may be correctly identified even when the product is unsupported. **ShopAssist:** Boeing is a manufacturer mention in an aircraft request; clarification prevents inappropriate shopping retrieval. **Trade-off:** deleting unsupported names helps a business-policy label while losing explicit intent. **References:** R3; ISSUE-07 in the issue investigation.

## 3. Slot filling

**Definition:** assigning extracted information to named fields. **Intuition:** fill a form from language. **Technical detail:** scalar slots constrain what can be represented; null means no resolved value, not an instruction to guess. Missing fields differ from explicit null during evaluation. **ShopAssist:** Nike or Adidas cannot be faithfully reduced to one brand scalar. **Trade-off:** arrays increase expressiveness but require versioned consumers and more validation. **References:** R1/R12; schema review.

## 4. Intent classification

**Definition:** selecting the requested task or product/domain intent. **Intuition:** decide which kind of shopping request this is before filtering. **Technical detail:** class labels may be ambiguous or outside the supported taxonomy; classifiers need abstention/clarification rather than forced assignment. **ShopAssist:** toy airplane should not become Automotive just because airplane is a vehicle word. **Trade-off:** clarification preserves precision at the cost of additional user interaction. **References:** R3; new fixture annotation rubric.

## 5. Hard constraints

**Definition:** mandatory conditions that eligible products must satisfy. **Intuition:** a product violating a stated budget is not acceptable merely because it looks similar. **Technical detail:** eligibility can be written H(p)=∧j h_j(p); extraction and SQL operator mapping must both be correct. **ShopAssist:** under2000 means price<2000, while up to2000 means≤2000 in a contract supporting flags. **Trade-off:** inaccurate filters eliminate relevant products; missing filters violate intent. **References:** contract review; R1.

## 6. Soft preferences

**Definition:** desirable attributes or use cases used for ranking. **Intuition:** comfortable matters even when there is no reliable comfortable=true catalog column. **Technical detail:** preferences are positive evidence, distinct from item identity, mandatory numeric slots and rejection. **ShopAssist:** shoes suitable for running carries an intended-use preference; running shoes is a class phrase. **Trade-off:** strings are flexible but inconsistent phrasing complicates evaluation and embedding. **References:** R3; ISSUE-01.

## 7. Product type recognition

**Definition:** identifying the requested item class at an appropriate level of specificity. **Intuition:** distinguish an analog watch from a watch merely preferred to look classic. **Technical detail:** modifiers can define a class or describe an attribute depending on context. A global blacklist cannot decide this reliably. **ShopAssist:** removing analog from preferences when product_type is analog watch fixes HELD005; removing running from every phrase deletes valid use intent. **Trade-off:** taxonomy precision needs reviewed conventions. **References:** R3; rule ablation results.

## 8. Negation scope detection

**Definition:** determining which concept a negative cue applies to. **Intuition:** not only running shoes does not reject running shoes. **Technical detail:** detect cue, subject and scope together; qualifiers, coordination and double negatives change meaning. Research treats scope boundaries as a separate prediction problem. **ShopAssist:** without leather rejects leather; not under2000 sets a lower price condition; not too expensive is qualitative. **Trade-off:** narrow rules are inspectable but incomplete; broader parsers need data and evaluation. **References:** R5 and rule invariance tests.

## 9. Structured outputs

**Definition:** model output constrained to a machine-readable structure. **Intuition:** ask for a form instead of an essay. **Technical detail:** provider schema support can restrict syntax/types; it does not establish true category, brand or preference values. Transport errors and truncated or invalid responses still need explicit handling. **ShopAssist:** a valid object naming Honda as a seat-cover manufacturer can be semantically wrong. **Trade-off:** structure lowers parsing burden but can hide mistakes behind plausible fields. **References:** R1/R2.

## 10. JSON Schema

**Definition:** a vocabulary for specifying object properties, required fields and allowed values/types. **Intuition:** a blueprint for the JSON form. **Technical detail:** provider support may cover only a subset; schemas with defaults can permit omitted slots. Required versus nullable are different: a required nullable field must exist but may contain null. **ShopAssist:** D1 requires product_type and exclusions without adding new semantic fields. **Trade-off:** larger schemas cost input tokens and may exceed provider capabilities. **References:** R1/R2.

## 11. Pydantic validation

**Definition:** parsing Python data into declared models with validators. **Intuition:** reject impossible values before they reach consumers. **Technical detail:** ordinary mode may coerce values; validators can normalize, discard extra properties and truncate lists. Thus validated output can differ from raw JSON. Negative-price checks do not automatically prove finite-number enforcement. **ShopAssist:** both public schemas limit preference lists to ten. **Trade-off:** convenient repair can hide omission or information loss; strict policies need compatibility review. **References:** R12 and actual schemas.py.

## 12. Prompt engineering

**Definition:** designing instructions and context to improve task performance. **Intuition:** explain boundaries precisely rather than continually adding prose. **Technical detail:** hold model/schema/temperature/data fixed while changing definitions, examples or task decomposition. A single-call staged prompt is an instruction strategy, not observable proof of the model's internal reasoning. **ShopAssist:** C2 defines manufacturer versus compatibility target. **Trade-off:** longer prompts can help scoping but increase tokens and overfitting. **References:** R3 and candidate registry.

## 13. Zero-shot prompting

**Definition:** giving instructions without solved task demonstrations. **Intuition:** rely on definitions and existing model capability. **Technical detail:** the schema itself remains conditioning information; zero-shot does not mean no context. Measure on unseen queries against the same controls. **ShopAssist:** compact rules define constraints and negation without full worked examples. **Trade-off:** lower input cost can come with weaker handling of subtle policy distinctions. **References:** R3.

## 14. Few-shot prompting

**Definition:** supplying a small set of labeled demonstrations in the prompt. **Intuition:** show what good extraction looks like. **Technical detail:** consistent, varied examples condition field choices and annotation policy; copied evaluation cases contaminate evidence. **ShopAssist:** C4 shows an inclusive laptop budget, a strict chair bound and foreign currency clarification. **Trade-off:** examples cost input tokens and can bias the model toward their domains. **References:** R3; dataset methodology.

## 15. Contrastive prompting

**Definition:** showing similar inputs whose correct outputs differ. **Intuition:** teach the boundary between two easily confused meanings. **Technical detail:** minimal contrasts isolate a semantic distinction rather than merely demonstrate frequent cases. **ShopAssist:** running shoes, shoes suitable for running, shoes not running shoes and not only running shoes have different class/preference/exclusion assignments. **Trade-off:** a contrast clarifies one boundary without proving general scope competence. **References:** R3/R5; C3 candidate.

## 16. Temperature

**Definition:** a parameter scaling token logits before sampling. **Intuition:** change how concentrated the choice distribution is. **Technical detail:** for T>0, p_i(T)=exp(z_i/T)/Σj exp(z_j/T); T→0 tends toward greedy selection subject to implementation details. This says nothing about semantic optimality. **ShopAssist:** compare0/.5/1 on identical E5-B architecture with repetitions. **Trade-off:** diversity may improve or harm extraction; hosted T0 is not a reproducibility guarantee. **References:** R4; temperature audit.

## 17. Token sampling

**Definition:** selecting successive output tokens from model probabilities. **Intuition:** each local choice shapes the remaining sentence or JSON. **Technical detail:** sampling policies and constrained output support influence allowed choices; greedy local argmax does not maximize task accuracy or necessarily global sequence probability. Providers may not expose all decoding internals. **ShopAssist:** correct JSON structure does not choose the right exclusion target automatically. **Trade-off:** repeated samples add cost and may repeat the same systematic error. **References:** R4/R8, whose self-consistency evidence concerns reasoning tasks rather than shopping extraction.

## 18. Reproducibility

**Definition:** enabling another run or auditor to reconstruct configuration, data and conclusions. **Intuition:** save more than a final percentage. **Technical detail:** hash actual prompt/schema/query/settings, record SDK/model version, raw and normalized output, attempts, timestamps and scorer policy. A mutable cloud model may still change. **ShopAssist:** the new runner has persistent budget and task fingerprints; cache replay cannot count as independent sampling. **Trade-off:** provenance costs storage and requires privacy controls. **References:** R2/R6; runner tests.

## 19. Hallucination

**Definition:** generating unsupported or invented information. **Intuition:** a vague cheap request does not justify inventing a2000 budget. **Technical detail:** reference-relative false-positive hard atoms are a useful proxy; wrong labels, missing policy and semantic ambiguity can also produce such counts. Separate invented values from errors of attachment. **ShopAssist:** Honda as accessory brand is a wrong role assignment; an unstated rating threshold is invented. **Trade-off:** clarification reduces guessing but can burden users. **References:** R1/R3; per-case audit.

## 20. Rule-based NLP

**Definition:** interpreting text with explicit patterns, dictionaries or logic. **Intuition:** handle clear, bounded patterns consistently. **Technical detail:** a deterministic function always applies the same rule, but the rule's linguistic assumption may be wrong. Bind an operator to its number and scope before overwriting extraction. **ShopAssist:** at least900 watts must not become min_price900. **Trade-off:** inspectability and low cost compete with limited coverage and brittle scope. **References:** R5; rule audit.

## 21. Hybrid LLM systems

**Definition:** combining learned extraction with deterministic validation or correction. **Intuition:** use language competence and explicit invariants together. **Technical detail:** distinguish format/range checks from semantic rewrites; preserve original output and correction rationale, then revalidate the final object. **ShopAssist:** E6 retains named manufacturers and clarifies foreign currencies, without broad intent deletion. **Trade-off:** every correction can introduce an error; deployment needs paired evidence beyond already seen examples. **References:** R1/R5; conservative rules.

## 22. Ablation studies

**Definition:** changing or removing one component to identify its contribution. **Intuition:** find which part actually helps. **Technical detail:** compare identical inputs/raw responses and hold the other components fixed; report fixes, newly introduced errors and interactions. **ShopAssist:** price, negation, product cleanup, brand and currency rules replay the same stored raw20. **Trade-off:** combined effects need not equal sums of individual gains. Whole-query EM can hide additional damage to an already wrong row. **References:** R6/R7; ablation JSON.

## 23. Ground truth

**Definition:** reviewed reference labels representing the evaluation policy. **Intuition:** the answer key is a human judgment, not automatic truth. **Technical detail:** annotate independently of predictions, record conventions and adjudicate disagreements before scoring. **ShopAssist:** unsupported aircraft attributes and feature-versus-attribute typing need policy review; the80 new cases have one author only. **Trade-off:** independent review costs time but improves validity more than simply increasing sample count. **References:** methodology; R6/R7 for evaluation implications.

## 24. Evaluation leakage

**Definition:** exposing evaluation information to the process selecting a system. **Intuition:** an exam no longer measures unseen competence after practicing its answers. **Technical detail:** exact duplicates are one form; related templates, repeatedly inspected errors and candidate selection on a final set also matter. **ShopAssist:**13/15 old dev queries overlap original50; the oldheld20 is now diagnostic data. **Trade-off:** reuse is efficient for debugging but requires a new locked test for adoption. **References:** dataset integrity and methodology.

## 25. Precision, recall and F1

**Definition:** precision measures correctness of predictions; recall measures recovery of expected items; F1 balances them. **Intuition:** avoid both extra and missed attributes. **Technical detail:** P=TP/(TP+FP), R=TP/(TP+FN), F1=2TP/(2TP+FP+FN). Micro pools counts; macro averages query scores. Empty-set and failure conventions must be explicit. **ShopAssist:** exclusion macro90% but micro28.57% reveals sparse negatives. **Trade-off:** neither alone captures user-level correctness. **References:** scoring.py; R6/R7.

## 26. Exact match

**Definition:** all applicable scored fields must match for a query to pass. **Intuition:** one wrong filter can make the whole request unusable. **Technical detail:** EM=N⁻¹Σi 1[fields equal and valid]. Define the field set before comparison: common fields versus fullv2 slots versus lexical wording. **ShopAssist:** oldheld20 shared EM40%→60%; v2 full EM50% has more fields. **Trade-off:** EM is interpretable but strict, sensitive to policy and unforgiving of partially useful outputs. **References:** results; R7.

## 27. Semantic equivalence

**Definition:** different wording that preserves the same relevant meaning. **Intuition:** lumbar support and with lumbar support may deserve supplementary credit. **Technical detail:** predeclare narrow equivalence classes or adjudicate blindly; do not use broad similarity that accepts opposite polarity or changes numeric operators. **ShopAssist:** supplementary soft F1 handles the lumbar variant while strict labels remain unchanged. **Trade-off:** lexical scoring overpenalizes paraphrases; permissive semantic scoring can hide real errors. **References:** R1 for semantic validation limits; methodology equivalence policy.

## 28. Generalization

**Definition:** performance on relevant queries beyond those used for refinement. **Intuition:** fixing a known sentence is different from learning a robust rule. **Technical detail:** freeze candidate selection on development/validation before testing fresh data; cover domains, language and constructs, and state distribution limits. **ShopAssist:**18/18 preserved oracle structures does not measure multilingual Gemini extraction. **Trade-off:** broader evaluation costs annotation and API budget; handcrafted coverage still differs from real users. **References:** R6/R7; robustness protocol.

## 29. Statistical uncertainty

**Definition:** uncertainty about population performance or treatment effects inferred from finite samples. **Intuition:** ten successes in twenty is not proof of an exact50% future rate. **Technical detail:** Wilson intervals estimate query proportions; paired bootstrap resamples query differences; repeated requests must remain in query clusters. **ShopAssist:** common EM effect+20points has bootstrap95 interval−5 to+45points. **Trade-off:** an inconclusive result can be useful without proving improvement or equivalence. **References:** R6/R7.

## 30. Latency and token economics

**Definition:** measuring time and resource cost per useful extraction. **Intuition:** a cheap wrong answer may cost more per correct request. **Technical detail:** distinguish API round-trip, retries, pacing, local processing and cache lookup; count observed tokens before validation and reserve unknown usage. Useful ratios are observed tokens/valid extractions and observed tokens/correct extractions. **ShopAssist:** old1480.8ms stored median is not fresh uncached inference evidence. **Trade-off:** repetition/retries improve evidence or availability but consume budget and increase tail time. **References:** R2/R9/R10/R11; runner methodology.

## Putting the concepts together

Language → extraction → validated representation → eligibility gate → reviewed downstream filters/ranking. Each arrow can lose meaning. Evaluate fields and full requests; inspect corrections; preserve raw evidence privately; report failures and uncertainty. The current decision is PARTIAL, with productionv1 retained and larger live work deferred. This is a defensible engineering result rather than evidence that semantic optimization has already succeeded.
