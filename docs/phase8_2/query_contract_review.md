# Phase 8.2 query contract review

Date: 2026-10-09. **Accepted production contract: existing v1.0.0**, `QueryUnderstandingOutput` inside `QueryUnderstandingResult`. Existing v2.0.0 remains experimental. D1 RequiredV2 is an isolated required-slot research model, not a public contract version or production migration.

## Current fields and implemented behavior

| Meaning | Productionv1 | Experimentalv2 | Limitation |
| --- | --- | --- | --- |
| Requested item | semantic_query text | product_type plus semantic_query | Item class and useful descriptors need clear annotation |
| Positive hard slots | category,brand,min/max_price,min_rating,currency | Same slots | Single brand/category cannot encode alternatives |
| Price operators | No flags | min_inclusive/max_inclusive, defaulttrue | v1 loses strict under/above intent |
| Positive attributes/use | soft_preferences string list | Same list | Validators deduplicate/lowercase and truncate at10 |
| Rejections | Embedded text only | exclusions[target_type,value] | Scope and target typing can still be wrong |
| Clarification | needs_clarification/reason | Same | No invariant currently requires a nonempty reason |
| Diagnostics | query,raw_response_text,model,latency,tokens,is_valid,errors | Research records separately | Result serialization still includes raw query/response |

Public schemas ignore extra fields; Pydantic validation normally permits coercion. Category/brand strings are not schema enums. Negative prices, reversed ranges and ratings outside1–5 fail, but finite NaN/infinity enforcement is not explicit. Empty semantic text can become an unspecified fallback; schema-valid is not semantically trustworthy. Omitted optional fields take defaults. RequiredV2 addresses a few omissions only; typed preferences or scope/source spans are deferred until measured benefit supports their complexity.

## Semantic conventions under review

Product type names the requested item class. Running shoes is a class; shoes suitable for running is shoes plus intended-use preference. Wireless/noise cancelling can be separate attributes; class specificity requires a reviewed rubric. Canonical English category/product type and literal source-language preference policy are used in the new fixtures, not a new production multilingual guarantee.

Exclusions preserve typed rejected values separately from positive preferences. Attribute and feature overlap is an annotation risk. Not only/not necessarily is not rejection; not too expensive is qualitative; double negatives require scope. No substring rule can safely replace scope interpretation. A literal manufacturer outside the catalog remains useful extracted intent; unsupported requests must be gated before filter activation. Compatibility targets such as Honda City or iPhone must not become the accessory's requested brand. Multi-brand/product alternatives require clarification with current scalar representation.

For v2: under/below imply max_price with max_inclusive=false; up to/at most implytrue. Above implies min_inclusive=false; at least/no less than/not under implytrue. Last explicit correction takes precedence. Flags are inapplicable when the numeric bound is null. Watts, years and stars are not prices. Currency conversion is absent; do not apply foreign numeric prices to an INR catalog without clarification.

## Structural versus semantic adaptation

`to_v1()` creates an object accepted by v1, but discards product_type and both boundary flags. It appends exclusion words as soft strings; target type, enforcement and polarity structure disappear, and ten-item truncation can drop negatives. For a v2 request under2000 excludingrunning shoes, the v1 object carries only max_price2000 and a negative string: an inclusive SQL consumer may accept exactly2000, and a preference embedder may accidentally rank running shoes positively. Do not claim full backward semantic compatibility.

## Phase9 and Phase10 interfaces

Phase9 may prototype against documented v1 positive preference strings with explicit gating for is_valid=false or needs_clarification=true. Preserve query semantics and avoid embedding exclusion strings as positive evidence. Semantic query needs a separate retention and retrieval-content policy. Full quality acceptance is not established by the current samples.

Phase10 must construct parameterized filters against actual `product_name`, `category`, `brand`, `discounted_price` and `rating` columns. Do not treat LLM-generated SQL as executable. For an eventually accepted v2 contract choose > versus≥, < versus≤ according to active flags; preserve rejection intent using reviewed product metadata/evidence. Simple title substring exclusion may overexclude or miss synonyms. INR-only filters must gate foreign currency. Product rating null handling and strict user rating intent must be defined even though the proposal describes rating mainly as a ranking signal. This is interface guidance; no Phase9 embeddings, Phase10 retrieval or database mutation was implemented.

## Migration requirements

Before adoption: independently validate v2 semantics, choose canonical class/exclusion policy, verify all consumers, version any breaking schema change, provide dual-read adapters with explicit loss warnings, add consumer tests for boundaries/negation/clarification, and obtain approval before switching production consumers. Consider a minimal future amendment requiring finite numbers, explicit required slots and clarification consistency; measure provider schema compatibility and token cost first. Retain v1 as production until these gates pass. No consumer may infer quality, security or catalog support solely from Pydantic success.
