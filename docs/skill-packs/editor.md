# Edit and verify a skill

Find the active source with the task catalog and check its owner and upstream. Determine which assistant reads it, where bundled references resolve and whether the entry points to another copy. Edit the maintained project file once. For a vendor-supplied skill, resolve its publisher's supported update channel and review the change there.

Record the installed tag or commit, the comparable upstream tag or commit, the date and the result of a live check. Use the publisher's release for a versioned plugin and the exact tracked path for a project skill. A cache directory called `local`, a version from another channel or an unavailable upstream leaves freshness unknown. Check whether the project intentionally pins an older compatible release before any update.

Exercise the change with one realistic prompt that should select it and a nearby prompt that should select another skill. Validate the manifest, follow its relative links, run its command in the supported environment, then inspect the result through the consumer. Record the example, observed result and rollback revision. A failed connection, a missing source or an outdated command is an open finding even if the manifest parses.

Use these publisher-maintained references to evaluate additions.

- Portable metadata and layout. [Agent Skills specification](https://agentskills.io/specification)
- Codex catalog. [OpenAI skills](https://github.com/openai/skills)
- Authoring and evaluation examples. [Anthropic skills](https://github.com/anthropics/skills)
- Server discovery and publisher details. [MCP Registry](https://github.com/modelcontextprotocol/registry)
