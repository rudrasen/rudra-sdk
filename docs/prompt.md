
<!--your actual decision reasoning — the why behind namespaced resources, why you chose TTL+jitter, why filtering lives in FilterOptions. Those decisions are yours. Claude just formats them.

The signal examiners are reading for in design.md is: does this person understand the tradeoffs they made, or did they just let a tool generate an SDK and documentation they can't defend?
-->

Create a structured design.md with information about my SDK design based on my directives and include the reasoning and tradeoffs. catch any gaps or assumption in my directives, reason or tradeoffs then ask clarify to extract the reasoning and tradeoff    
- Architecture Use Namespaced Resources design pattern because it allows for 

- Data models 
- Authorization
- Caching  Strategy is based on  File-Based TTL with Jitter because

-----
Create a structured design.md with information about my SDK design based on my directives and include the reasoning and tradeoffs. catch any gaps or assumption in my directives, reason or tradeoffs then ask clarify to extract the reasoning and tradeoff and insert in relevant section in the design.md file.

Pattern: namespaced resources client.movies.list() / client.movies.get(id) / client.movies.quotes(id) client.quotes.list() / client.quotes.get(id)
Models: Pydantic v2. All response shapes mapped from real API fixtures.
Auth: Bearer token. Constructor arg with LOTR_API_KEY env var fallback. Fail fast at client init if neither is present.
Exceptions: SDK-specific hierarchy. LotRError (base) > AuthError, NotFoundError, RateLimitError, APIError, ValidationError. HTTP status → exception mapping lives exclusively in http.py. 401 and 404 are never retried regardless of retry config.
HTTP: requests.Session. Single HTTPClient class. No async in v1.
Filtering: FilterOptions Pydantic model with to_query_params() method. Supports: limit, page, offset, sort_by, sort_order, filter_field, filter_value.
Caching: not in v1. Document as v2 roadmap item in design.md.
Retry: optional RetryConfig passed at client init. Not required for v1 MVP. If included: exponential backoff, configurable max_attempts and retry_on status codes.
No CLI, no async, no additional endpoints beyond the 5 in scope.

---


# SDK design

---

# Architecture
architecture overview 
## Public API Design  
### Authentication  
auth pattern,
## Abstractions
why namespaced resources,

## Data Model


## Caching  
## Filtering 
how filtering works
## Error Handling and Retry Policy 
exception hierarchy rationale
## Testing Strategy 

## Project Structure

## v2 roadmap

 (async, caching, remaining endpoints).