# Soft Preference Representation Fundamentals

This guide describes how ShopAssist moves qualitative user preferences into the same vector space used for catalog text. Every stage remains a soft semantic signal; hard constraints require a separate, explicit consumer.

## 1. Soft preferences

**Definition:** Qualitative, subjective or usage-oriented desires such as “lightweight”, “comfortable”, or “for daily jogging”. **Intuition:** They describe what makes a product appealing after required filters are satisfied. **Technical view:** Phase 8 emits a list of phrases, not truth-valued product predicates. **Example:** `comfortable` for `running shoes`. **Implementation:** `QueryUnderstandingOutput.soft_preferences`. **Limit:** Extraction can omit or invent phrases; a valid model object is not a correctness guarantee.

## 2. Semantic representation

**Definition:** An encoding that maps text to a numerical space where related meanings tend to be near one another. **Intuition:** Different phrasings can point in a similar direction. **Technical view:** An encoder maps text (t) to (f(t)\in\mathbb{R}^{384}). **Example:** “daily jogging” may be related to running-shoe descriptions. **Implementation:** composed preference text then BGE. **Limit:** Similarity is learned association, not proof every requirement is met.

## 3. Text normalization

**Definition:** Deterministic cleanup that reduces formatting variation. **Intuition:** “ good   battery life ” and “good battery life” should match. **Technical view:** NFC Unicode normalization, trim, whitespace collapse, case-folding and stable de-duplication. **Example:** repeated `lightweight` appears once. **Implementation:** `normalize_preferences`. **Limit:** normalization must not remove negation, translate, or silently broaden a phrase.

## 4. Query composition

**Definition:** Combining preference phrases with the requested product context. **Intuition:** “lightweight” is less informative without “laptop”. **Technical view:** deterministic function (g(c,P)), here `P₁; P₂ — c`. **Example:** `lightweight; good battery life — laptop`. **Implementation:** `build_preference_query`. **Limit:** punctuation/order may affect a model; compare with controlled embedding pairs.

## 5. Query reformulation

**Definition:** Rewriting a query to make it clearer to a retrieval system. **Intuition:** Adding “with” or reordering can clarify relations. **Technical view:** changes input tokens before encoding, therefore potentially changes vector (f(t)). **Example:** keyword list vs natural phrase. **Implementation:** Phase 9 currently avoids generative rewriting. **Limit:** an LLM rewrite can invent conditions and is unnecessary for short deterministic lists.

## 6. Sentence embeddings

**Definition:** Fixed-length vectors for variable-length text. **Intuition:** A sentence becomes a point/direction in a learned space. **Technical view:** transformer token representations are pooled into one vector. **Example:** one 384-value vector for a preference query. **Implementation:** Sentence Transformers. **Limit:** information compresses; rare, negated or precise relations may be weakly represented.

## 7. Sentence Transformers

**Definition:** A Python framework for encoding text and comparing sentence vectors. **Intuition:** It packages a trained encoder behind `encode`. **Technical view:** model inference plus pooling and optional normalization. **Example:** `EmbeddingModel.encode_queries`. **Implementation:** reused from Phase 5/7. **Limit:** weights, library versions, device and preprocessing must match.

## 8. BGE embedding models

**Definition:** BAAI General Embedding model family trained for text retrieval. **Intuition:** The query-side encoder is trained to find related passages. **Technical view:** ShopAssist uses `BAAI/bge-small-en-v1.5`, with 384 dimensions. **Example:** preference query compared with `retrieval_text`. **Implementation:** existing `EmbeddingModel`. **Limit:** the English model may represent non-English text unevenly; this project has not measured every language.

## 9. Query and document encoding

**Definition:** Encoding queries and catalog documents, sometimes with different instructions. **Intuition:** The query asks for passages; product text is the passage. **Technical view:** ShopAssist encodes document `retrieval_text` raw and prepends `Represent this sentence for searching relevant passages: ` to queries. **Example:** Phase 9 uses the query side. **Implementation:** `DenseQueryEncoder`. **Limit:** identical dimensions alone do not prove compatible training or preprocessing.

## 10. Embedding-space compatibility

**Definition:** Query and document vectors share model weights, conventions and intended geometry. **Intuition:** Coordinates only compare meaningfully when both sides use the same map. **Technical view:** model, tokenizer, pooling, instruction and normalization are part of the vector contract. **Example:** same BGE version and query instruction against Phase 5 vectors. **Implementation:** adapter checks name and dimension; the local run generated 384D normalized queries with the shared Phase 7 encoder. **Limit:** the curated check did not benchmark all stored catalog vectors or retrieval behavior.

## 11. Vector dimensionality

**Definition:** Number of coordinates in a vector. **Intuition:** 384 numeric slots describe one point. **Technical view:** vector (v\in\mathbb{R}^{384}); pgvector schema is `vector(384)`. **Example:** every Phase 9 result must have exactly 384 values. **Implementation:** `validate_preference_vector`. **Limit:** same length does not imply same model space.

## 12. Vector normalization

**Definition:** Scaling a vector to a chosen norm. **Intuition:** Direction matters without magnitude dominating. **Technical view:** (\hat v=v/\|v\|_2); unit norm is approximately 1. **Example:** Phase 7 normalizes query vectors. **Implementation:** reused encoder and validation tolerance `1e-4`. **Limit:** normalization does not improve semantic meaning; zero/non-finite values are invalid.

## 13. Cosine similarity

**Definition:** Angle-based comparison of vectors. **Intuition:** Smaller angle means more aligned. **Technical view:** (\cos(x,y)=\frac{x\cdot y}{\|x\|_2\|y\|_2}); for unit vectors it equals dot product. **Example:** compare preference vector to product embedding. **Implementation:** Phase 7 `compute_similarity` and pgvector cosine distance. **Limit:** a high score is not a hard-constraint satisfaction certificate.

## 14. Preference-only versus contextual queries

**Definition:** Preference-only omits product type; contextual composition includes it. **Intuition:** “comfortable” could refer to shoes, chairs or headphones. **Technical view:** adding context changes the query vector and ranking distribution. **Example:** `comfortable` vs `comfortable — running shoes`. **Implementation:** contextual default preserves semantic query. **Limit:** context could overemphasize category; compare both using paired descriptions before claiming a winner.

## 15. Positive versus negative preferences

**Definition:** Positive phrases request a quality; negative phrases forbid or exclude something. **Intuition:** “leather” and “without leather” point in opposite directions. **Technical view:** dense encoding does not provide a guaranteed logical NOT operator. **Example:** `without leather` must not enter as a positive preference. **Implementation:** conservative guard returns unsupported for known patterns. **Limit:** regex is not general negation-scope parsing; exclusions belong in a typed, enforced contract.

## 16. Embedding semantic limitations

**Definition:** A vector approximates learned associations, not a symbolic list of obligations. **Intuition:** one phrase may dominate or disappear among others. **Technical view:** pooled vectors compress token interactions; cosine ranking is an approximate relevance signal. **Example:** a high “waterproof backpack” score does not verify a product specification. **Implementation:** Phase 10 should use hard filters/specification evidence separately. **Limit:** test on relevant/irrelevant pairs; never promise perfect semantics.

## 17. Batch embedding generation

**Definition:** Encode several texts in one model call. **Intuition:** batching reduces Python/model dispatch overhead. **Technical view:** tokenized examples share accelerator or CPU inference batches. **Example:** encode many curated preference queries with batch size 32. **Implementation:** adapter `encode_batch` uses shared `encode_queries`. **Limit:** current service-level `represent_batch` still invokes individual representations and does not yet coalesce calls.

## 18. CPU versus GPU inference

**Definition:** Execute model calculations on general CPU or accelerator. **Intuition:** GPU often handles parallel tensor math faster, while CPU is broadly available. **Technical view:** PyTorch device kernels and memory transfer affect latency. **Example:** Phase 7 auto-selects CUDA, MPS or CPU. **Implementation:** `resolve_device` and cached model; Phase 9 was measured on a CUDA RTX 3050 Laptop GPU. **Limit:** CPU latency was not measured, and performance depends on hardware, warmup, batch size and contention.

## 19. Embedding evaluation

**Definition:** Measure whether encoded queries rank curated relevant text above irrelevant text. **Intuition:** check a small set of known pairs before integration. **Technical view:** paired cosine/ranking comparisons under fixed model, text and composition. **Example:** comfortable running shoes versus industrial cabinet. **Implementation:** Phase 9 evaluated four authored pairs under three compositions; relevant text ranked higher in 12/12 comparisons. **Limit:** small curated tests do not predict catalog-wide recall or recommendation quality.

## 20. Relationship to hybrid retrieval

**Definition:** Combine semantic candidate scoring with structured constraints or lexical evidence. **Intuition:** semantic similarity finds “what feels right”; filters enforce “what must be true.” **Technical view:** Phase 10 can combine pgvector distance with validated SQL predicates and other signals. **Example:** filter to INR budget/category, then rank by preference vector. **Implementation:** Phase 9 returns vector and provenance only. **Limit:** Phase 9 does not perform hybrid retrieval; Phase 10 owns enforcement, candidate quality and evaluation.

## End-to-end mathematical view

For context (c), positive preference list (P=(p_1,\ldots,p_n)), deterministic composer (g), and encoder (f):

\[
q_p=g(c,P),\qquad v_p=\frac{f(q_p)}{\|f(q_p)\|_2},\qquad s(d)=v_p^\top v_d
\]

This defines a similarity signal only. Hard-constraint feasibility and typed exclusions are separate operations; unsupported intent must stop before retrieval.
