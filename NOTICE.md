# NOTICE

`partsmith` was inspired by and shares REST endpoint shapes with
[Svetlana-DAO-LLC/cad-agent](https://github.com/Svetlana-DAO-LLC/cad-agent)
at commit SHA `5bbf716870128af0e6e1ac49fff6a315e79a417a` (independently
audited 2026-06-08).

The implementation here is a clean-room rewrite: no source code was
copied or ported. The endpoint surface was preserved for compatibility
with tooling that targets cad-agent's REST shape. Underlying CAD
operations use [build123d](https://github.com/gumyr/build123d) directly,
without intermediate abstractions present in cad-agent.

Credit to the cad-agent author for the initial concept of wrapping
build123d behind a REST/MCP surface for AI-agent consumption.
