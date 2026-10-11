<h1 align="center">CodeParse</h1>

<p align="center">
  <img alt="Lines of Code" src="https://aschey.tech/tokei/github/cmgoffena13/codeparse?category=code">
  <a href="https://github.com/cmgoffena13/selene-ai/actions"><img alt="Build Status" src="https://github.com/cmgoffena13/codeparse/actions/workflows/build-release.yml/badge.svg"></a>
  <img alt="License" src="https://img.shields.io/badge/license-MIT-informational?style=flat">
</p>

CodeParse is a codebase indexer that gives agents fast, accurate, and compact context on your Python codebases while reducing token usage. It parses your codebase and stores the relationships of your code in a local SQLite database.

## Install MCP Server and Skill

1. Put the `codeparse` binary on your PATH (release asset or `make compile` → `dist/codeparse`).
2. `codeparse install`

## Benchmark Evaluation (in-progress)

Ten questions found in `eval/tasks.json` are evaluated against the [SQLMesh](https://github.com/TobikoData/sqlmesh) repo using a baseline agent and an agent with the CodeParse MCP server.

 - **AI Baseline**: Builtin tools
 - **AI w/ CodeParse**: Builtin tools and CodeParse MCP Server
 - **Total Tokens**: All tokens used by the agent to complete the task.
 
```
Cursor Benchmark Evaluation - Grok 4.7
----------------- Mean -----------------
AI Baseline Total Tokene: 393,530
AI w/ CodeParse Total Tokens: 265,867 (-32% reduction)
----------------------------------------

Claude Benchmark Evaluation - Opus 5.5 Medium
----------------- Mean -----------------
AI Baseline Total Tokene: XXXX
AI w/ CodeParse Total Tokens: XXXX
----------------------------------------
```

### Running the Evaluation

Cursor Default Model: `grok 4.7`  
Claude Defualt Model: `opus 5.5 medium`

 - `make eval-smoke cursor` will run all 10 questions and evaluate.
 - `make eval cursor` will run all 10 questions on repeat (10 times) and evaluate. 

