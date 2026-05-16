# Vidimus — 90-Day Launch Plan

> From empty repo to public launch with first 100 real users and at least one credible commercial conversation.

---

## North Star

By Day 90, Vidimus should be:

1. **Live on PyPI** with `pip install vidimus` working
2. **Public on GitHub** with ≥ 500 stars
3. **Used by ≥ 100 distinct workspaces** (telemetry opt-in)
4. **Featured in at least one HN front page** or Show HN top 5
5. **In active conversation with ≥ 3 prospective design-partner organizations** (one ideally in regulated finance)

Anything beyond is a bonus. Anything less is recoverable but signals we need to re-evaluate positioning.

---

## Phase 1 — Build the MVP in private (Days 1–30)

The goal of Phase 1 is to have a working, demoable Module A. **No public mention of the project yet.** Premature exposure with a broken MVP burns the launch opportunity.

### Week 1 — Foundation
- Snipe `vidimus.ai` domain, set up DNS, basic landing page (one paragraph + email capture)
- Create GitHub org `@vidimus-ai`, create private repo, set up CI skeleton
- Reserve PyPI name `vidimus` with a stub package
- Create Discord server (closed, invite-only for now)
- Set up `keys.txt` repo for public key directory

### Week 2 — Core primitives
- Pydantic schemas (Trace, Span, CalibratedMetric, Attestation) per [ARCHITECTURE.md](ARCHITECTURE.md) §3
- Merkle tree implementation + tests (use the Certificate Transparency test vectors to validate)
- Ed25519 signing + verification + test vectors
- DuckDB storage layer
- Basic CLI scaffold

### Week 3 — Evaluation pipeline
- Multi-judge runner (OpenAI + Anthropic + Gemini, async, with caching)
- Bootstrap CI computation
- Cohen's κ, Fleiss's κ, Krippendorff's α implementations (or use `krippendorff` package)
- First end-to-end happy path: trace → attest → verify

### Week 4 — Integration & polish
- `@vidimus.audit` decorator
- OpenTelemetry HTTP receiver
- One reference integration: Vidimus running on top of Opik traces, attesting them
- README and ARCHITECTURE drafted and reviewed
- Internal demo: full attestation lifecycle on 1,000 sample traces

**Phase 1 exit criteria:** Nathan can run `pip install vidimus-prerelease`, instrument a toy agent, generate a signed attestation, and verify it offline. End-to-end demo recorded as a 3-minute screencast.

---

## Phase 2 — Alpha with design partners (Days 31–60)

The goal of Phase 2 is to harden the product against real users and collect 3–5 testimonials before public launch. Still no public marketing.

### Week 5 — Design partner outreach
Target 10–15 personalized outreach messages to:

- 3 LLMOps practitioners on X with audience (look for people posting about Opik/Langfuse pain points)
- 3 compliance / GRC professionals in fintech or healthtech
- 2 academic labs working on LLM evaluation
- 2 contacts in regulated industries (U-Capital, a francophone fintech, anyone in your network)
- 2 wildcards (someone from a16z / Sequoia / Y Combinator portfolio doing LLM stuff)

Pitch: *"I'm building an open-source tool that adds cryptographic provenance and calibrated confidence intervals to LLM evaluation reports. I'd love 20 minutes to show you what I have and see if it would have been useful in [their specific situation]. No commitment, no sales."*

### Week 6 — Onchain anchor + smart contract
- Deploy `VidimusAnchor.sol` on BNB Chain testnet, then mainnet
- Deploy on Base, Ethereum mainnet (low priority; can wait if budget tight)
- Verify contracts on block explorers (Etherscan, BscScan)
- Add `--check-anchor` to CLI

### Week 7 — Documentation site
- `docs.vidimus.ai` with Mintlify, Docusaurus, or Astro Starlight
- Pages: Quickstart, Concepts, SDK Reference, CLI Reference, Architecture, FAQ, Threat Model
- At least one full tutorial: *"Add Vidimus to your existing Opik setup in 5 minutes"*
- Second tutorial: *"Publish a verifiable evaluation report for your RAG system"*

### Week 8 — Alpha feedback loop
- Ship to alpha users
- Office hours: 2 × 1-hour open Zoom sessions for alpha users to ask questions
- Fix the top 5 issues identified
- Get 3–5 written testimonials ("This solved X for us")

**Phase 2 exit criteria:** 5 users have run end-to-end attestations on their own data. 3 have given quotable feedback. Documentation site is live and complete.

---

## Phase 3 — Public launch (Days 61–90)

### Week 9 — Pre-launch content
- Blog post 1: *"The trust gap in LLM evaluation"* — the problem statement
- Blog post 2: *"Why your LLM-as-a-judge score is probably lying to you"* — the calibration argument
- Blog post 3: *"Cryptographic attestation for AI evaluations"* — the technical solution
- Record a polished 4-minute demo video
- Prepare HN Show HN draft
- Prepare X / LinkedIn launch threads (long-form, technical)
- Prepare cross-posts for r/LocalLLaMA, r/MachineLearning, r/ChatGPTCoding

### Week 10 — Launch week
**Monday:** Repo goes public. Soft-share to Discord and design partners. Fix any last-minute issues.
**Tuesday:** Show HN, X launch thread, LinkedIn post. Respond to every single comment.
**Wednesday:** Cross-post to relevant subreddits. Submit to AI/ML newsletters (Ben's Bites, TLDR AI, The Rundown, Import AI).
**Thursday:** Outreach to a16z/Sequoia/Greylock AI tech leads — *"we just launched, no fundraising, just want feedback."*
**Friday:** Recap blog post with launch metrics. Office hours.

### Week 11 — Sustaining content
- Integration tutorial: Vidimus + Langfuse
- Integration tutorial: Vidimus + LangSmith  
- Guest blog post on a partner site (Comet, LangChain, Pydantic, or similar — pitch them)
- Twitter Spaces / X audio: *"Verifiable AI evaluations — a discussion"*

### Week 12 — Commercial conversations
- Identify the 3 most engaged organizations from launch traffic
- Reach out for paid design partnerships ($5–25k) for tailored deployment / consulting
- Apply to YC, Antler, Entrepreneur First (whichever batch is open)
- Apply to Mozilla Builders, Apache Incubator (if the OSS path is preferred)

**Phase 3 exit criteria:** 500+ GitHub stars, 100+ workspaces, at least one signed commercial conversation, and a clear answer to *"is this big enough to deserve more than a side project, or is it a feature waiting to be absorbed?"*

---

## Distribution channels — ranked by expected ROI

1. **Hacker News (Show HN).** Single highest-leverage launch surface for developer-tooling OSS. Land here once, well-prepared. Best windows: Tue–Thu, 9–11 ET.
2. **X / Twitter technical threads.** Tag the right people (Langfuse, Comet, LangChain, Helicone founders, OTel maintainers). Don't @-ping them, quote-relevant-tweet instead. Audiences: ~5–10k developers reachable in week 1.
3. **r/LocalLLaMA.** Most engaged technical audience in LLM-land. Post once, polished, expect ~100 upvotes if hitting a real pain point.
4. **r/MachineLearning.** More academic, harder to win. Post once with the calibration angle (research-flavored), not the crypto angle.
5. **AI/ML newsletters.** TLDR AI, Ben's Bites, Import AI, The Sequence. Submit launch day, expect 1 in 4 to feature.
6. **LinkedIn long-form.** Higher signal-to-noise than X for compliance / GRC audience. Cross-post the technical thread with a compliance framing.
7. **Direct outreach to design partners.** Slow, but highest conversion rate. Best ROI per hour spent in Phase 2.
8. **Conference talks (Phase 4+).** Submit to PyCon, KubeCon, Strange Loop, Real World Crypto. CFP cycles are 4–6 months out, plant seeds now.

Channels **NOT** to invest in early:

- Product Hunt (wrong audience for technical OSS dev tools)
- Dev.to / Medium republishing (low signal)
- Generic AI Discord servers (saturated, low conversion)
- TikTok / YouTube short-form (wrong format for the message)

---

## Target audience segments

### Primary: senior backend / ML platform engineers at AI-forward companies
They run Opik, Langfuse, or LangSmith today. They feel the pain of explaining LLM behavior to non-technical stakeholders. They will land on the repo, read the comparison table, install in 10 minutes, and tweet about it if it works.

### Secondary: compliance, risk, GRC leads in regulated industries
They are not on HN. They are on LinkedIn. They will not install the tool themselves but will forward it to the technical team. Message them with the audit-trail framing, not the cryptography framing.

### Tertiary: academic researchers in LLM evaluation
They will love the calibrated-uncertainty argument. They write the papers that get cited. A single research citation in a top-tier venue is worth more than 1,000 stars for long-term credibility.

### Wildcards: crypto/web3 builders, AI safety researchers
The on-chain anchor angle resonates with crypto-natives. The threat-model rigor resonates with AI safety folks. Neither is the primary market, but both will amplify if hit correctly.

---

## KPIs to track weekly

| Metric | Phase 1 target | Phase 2 target | Phase 3 target |
|---|---|---|---|
| GitHub stars | n/a (private) | n/a (private) | 500 |
| PyPI downloads (weekly) | 0 | 50 (alpha users) | 1,000 |
| Distinct workspaces (telemetry) | 1 | 5 | 100 |
| Discord members | 5 | 25 | 200 |
| Documentation page views | n/a | 200 | 5,000 |
| Design-partner conversations | 0 | 5 | 10 |
| Commercial inquiries | 0 | 1 | 3 |
| Press / newsletter mentions | 0 | 0 | 5 |

Track these in a single Notion / Google Sheet. Update every Monday. If three consecutive weeks miss target by > 30%, stop and re-evaluate strategy rather than working harder.

---

## Risks and mitigations

1. **A competitor announces something similar before launch.** Mitigation: don't delay launch waiting for "more polish." Ship at 80%. The cryptographic primitives and the calibration methodology are defensible — they require domain depth a fast-follower can't fake.

2. **HN ignores the launch.** Mitigation: HN is one channel of seven. If Show HN flops, double down on X technical threads and direct outreach. The compounding curve from design partners is independent of HN.

3. **The cryptographic story is too niche for most users.** Mitigation: lead with the calibrated-uncertainty story in marketing. Cryptography is the moat; calibration is the wedge. *"Stop trusting LLM-judge scores without confidence intervals"* is the headline; signed attestations are paragraph two.

4. **Nathan burns out at month 2.** Mitigation: hard cap of 15 hours/week. Saturday is mandatory rest day. If burnout signals (poor sleep, missed AI Capital reviews, thesis slipping) appear, immediately drop to maintenance mode and reassess.

5. **The first design partner has a contentious requirement (e.g. SOC 2, on-prem only) that derails the roadmap.** Mitigation: keep the OSS roadmap separate from any one customer's roadmap. Paid features that diverge from the OSS roadmap go in a separate `vidimus-enterprise` repo or fork. The OSS project must remain useful to everyone.

---

## What happens after Day 90

If Phase 3 exit criteria are met → Phase 4 is **Module B (`vidimus.optimize`)** development with a public roadmap, hiring a part-time contributor, and pursuing one of: YC / Antler application, Mozilla Builders grant, or paid pilot revenue from design partners.

If exit criteria are missed → conduct an honest retrospective. Likely options: pivot the positioning (e.g. lean harder into one segment), absorb the project as a feature into the AI Capital IR platform (cryptographic attestations of fund performance), or quietly maintain it as a portfolio piece while reallocating time to the RIA path.

Either way, no decision is regretted. The cost of the first 90 days is bounded; the optionality unlocked is enormous.
