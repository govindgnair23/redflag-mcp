---
date: 2026-04-23
topic: general-chat-aml-redflag-retrieval
---

# General-Chat AML Red Flag Retrieval

## Problem Frame

Compliance analysts and BSA officers need to find the right AML red flags quickly from conversational interfaces such as Claude and ChatGPT. The current server is useful for targeted semantic search, but the end-user value depends on two things that generic search tools handle inconsistently: helping vague users narrow their question before retrieval, and returning sourced red flags with enough explanation that analysts can quickly judge fit.

Because the primary distribution target is hosted connectors for mainstream chat users, the core experience must work even when MCP clients only support tool calling reliably. Richer MCP features may improve the experience in some environments, but they cannot be required for the main product value.

## Requirements

**Core Analyst Workflow**
- R1. A compliance analyst can ask a broad AML question in a hosted chat client and get relevant red flags without needing to know the corpus structure, taxonomy, or source documents in advance.
- R2. When the analyst's question is vague or underspecified, the experience asks follow-up questions before retrieval to narrow the search using product subtype, customer profile, geography, and other material context.
- R3. When the analyst's question is already specific enough, the experience skips follow-up questions and retrieves results directly.

**Search Results and Source Trust**
- R4. Retrieved results present red flags with direct source citations and clickable links back to the originating regulatory or guidance document; semantic search results are ranked, while exact metadata results are returned in deterministic filtered order.
- R5. Each result includes a short "why this fits" explanation tied to the analyst's stated context so the user can quickly judge relevance without reading the full corpus entry first.
- R6. The experience exposes a simple way to inspect source coverage, such as seeing which source documents are in the corpus and navigating from a result back to its source set.
- R7. When the analyst's request maps exactly to available metadata filters, the experience can return matching red flags through direct metadata filtering without invoking semantic embedding search.

**Compatibility and Product Shape**
- R8. The baseline end-user workflow must rely only on MCP capabilities that are broadly dependable in mainstream hosted chat clients, with tool calling treated as the compatibility floor.
- R9. Any use of richer MCP features such as resources, prompts, elicitation, or sampling must be strictly additive: the core analyst workflow remains complete and useful when those features are unavailable.
- R10. Client-specific enhancements may be offered in environments with stronger MCP support, but they must improve discoverability, trust, or speed rather than creating a separate primary workflow.

## Success Criteria

- A compliance analyst with a vague prompt such as "what red flags apply to my crypto product?" is guided into a narrower query before retrieval and receives meaningfully better results than a direct broad search.
- A compliance analyst with a specific prompt receives sourced results directly, without unnecessary follow-up friction.
- A compliance analyst asking for exact metadata criteria such as "high-risk depository structuring red flags" receives direct filtered results rather than semantically ranked approximations.
- Analysts can understand why a result was returned and can open the underlying source document from the answer.
- The hosted-connector version remains useful even if the client ignores MCP resources, prompts, elicitation, or sampling.

## Scope Boundaries

- The product does not depend on coding-agent-only affordances to deliver its core value.
- The product does not require server-side LLM orchestration during query handling if the client can already manage the consultation through tool guidance.
- The product does not attempt to replace broader AML research, policy drafting, or transaction monitoring rule design; it focuses on finding and returning relevant red flags with source trust.
- Rich interactive UIs, write actions, and workflow automation are out of scope for the first version unless they materially improve the analyst's retrieval experience.

## Key Decisions

- **General chat users first**: The first-class user is a compliance analyst in a hosted Claude or ChatGPT-style experience, not a coding-agent user in a local desktop workflow.
- **Consultation before search for vague prompts**: The default behavior should gather missing context first because broad AML prompts otherwise produce generic retrieval.
- **Results need explanation, not just matches**: Returning only ranked red flags is not enough; brief relevance explanations are part of the user value.
- **Exact metadata filters should bypass semantic search**: When the user supplies structured criteria that map cleanly to stored metadata, direct filtering is more predictable than embedding search.
- **Tools-first compatibility baseline**: The core product should assume tool support is available and treat other MCP features as optional enhancements because cross-client support is still uneven.
- **Richer MCP features are for acceleration, not dependency**: Resources, prompts, and other features should reduce clicks or improve inspection where supported, but the main experience cannot break without them.

## Dependencies / Assumptions

- Hosted Claude and ChatGPT integrations will continue to support remote MCP tool calling, though support for other MCP features may vary by client and plan.
- Source links remain stable enough to serve as durable citations for analysts.
- The corpus remains curated so that returned red flags are authoritative enough to justify a focused trust-and-citation experience.

## Alternatives Considered

- **Tools-only minimalism**: Keep the server limited to search/get/list tools and avoid additional MCP features entirely. This is compatible, but it leaves source browsing and inspection value on the table.
- **Feature-rich MCP-first design**: Lean on resources, prompts, elicitation, and sampling to create a richer guided workflow. This is attractive in stronger clients but too risky as the primary path for mainstream hosted chat users.
- **Recommended direction**: Keep the baseline tools-first workflow, then layer on a small number of optional MCP-native enhancements that improve source discoverability and guided retrieval where clients support them.
- **Direct filter retrieval**: Add metadata-only retrieval alongside semantic search so exact structured requests return deterministic filtered records instead of approximate semantic rankings.

## Outstanding Questions

### Deferred to Planning
- [Affects R2, R7][Technical] How much of the consultation flow should remain in tool descriptions versus being represented as explicit MCP prompts for clients that support prompt discovery?
- [Affects R4, R6, R9][Technical] Whether source inspection is better exposed first as additional tools, MCP resources, or both, given the compatibility target.
- [Affects R5][Needs research] What result explanation style best helps compliance analysts assess fit quickly without sounding speculative or overstating confidence.
- [Affects R8, R9, R10][Needs research] Which MCP features are actually surfaced to end users today in the target Claude and ChatGPT connector experiences, and how consistently.

## Next Steps

-> /ce:plan for structured implementation planning
