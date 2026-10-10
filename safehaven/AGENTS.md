# SafeHaven integration rules
- Keep SafeHaven as an independent TanStack Start app alongside Orion's existing applications so existing routing and API contracts remain intact.
- Use shared frontend context for checklist, offline preview and alerts so state stays consistent across routes.
- Each screen has its own TanStack route and leaf metadata so pages remain independently shareable.
- Initialize Google Maps only after hydration and retain demo labels so illustrative guidance is never confused with verified emergency information.
- Never connect Orion risk scores directly to SafeHaven safety scores because their directions are opposite.
