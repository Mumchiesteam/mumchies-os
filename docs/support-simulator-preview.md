# Mumchies support simulator — development checklist

## Available now
- Mumchies OS navigation entry: **Support Simulator** (development branch only).
- Authenticated API: `POST /api/v1/support/simulator/message` with `{"message":"Where is my order?","mode":"bot"}`.
- Fixed FAQ response, conservative human escalation, and simulated staff replies.
- Offline HTML demonstration can be distributed separately for testing without deployment.
- No Meta, OpenAI, Shopify, or actual customer messaging.

## Test cases
1. Product question: `Does your laddu have sugar?` — sample FAQ (product fact must be approved).
2. Order tracking: `Where is my order?` — human takeover.
3. Refund/damage: `I want a refund` — human takeover.
4. Human request: `Can I speak to a human?` — human takeover.
5. Any later customer message after takeover — no bot reply.
6. Simulated staff reply — shown as staff, never sent to WhatsApp.
7. Reset — creates a fresh local test conversation.

## Release gates
- GitHub Actions support backend tests and frontend build must pass on this branch.
- Confirm authentication/CSRF behavior in a nonproduction deployment.
- Product facts, policies, language coverage, and handover wording require Mumchies review.
- Database migration and webhook ingestion are **not** included in this simulator release.
- Keep `support_ai_enabled=false` and `whatsapp_webhook_enabled=false` until explicitly approved.
- Do not merge into `main` or deploy to production without approval.

## Preview deployment
Use a separate nonproduction frontend/backend environment pointed at a nonproduction database and test credentials. Do not use live Meta credentials or change the existing WhatsApp Business app. A GitHub branch by itself is not a hosted preview URL.
