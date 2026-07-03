# Quality Guidelines

> Code quality standards for backend development.

---

## Overview

<!--
Document your project's quality standards here.

Questions to answer:
- What patterns are forbidden?
- What linting rules do you enforce?
- What are your testing requirements?
- What code review standards apply?
-->

(To be filled by the team)

---

## Forbidden Patterns

<!-- Patterns that should never be used and why -->

(To be filled by the team)

---

## Required Patterns

<!-- Patterns that must always be used -->

### Deterministic PRD Facts Parsers

When a verify guard can be decided from PRD text by deterministic parsing, put
the parser in a shared facts helper instead of embedding a one-off regex in the
guard. Current owner:
`src/testcase_generator/services/prd_facts.py:48`.

Contracts:

- Incomplete fact sources such as `等`, `见外部目录`, `见巨量`, and
  `参考第三方目录` are not closed sets; they can only support values that are
  directly present in evidence.
- Closed enum checks must require a complete source and at least two parsed
  values before treating an assertion value as out-of-enum.
- Numeric upper-bound checks must preserve semantic units. `1000个区县` is a
  `地区` bound, not a generic `个` bound; `200条地区字符串` is also a `地区`
  bound. Counter words (`个` / `条`) are quantifiers, not the business unit.
- Unit alternatives must be longest-first where one term prefixes another:
  `字符` before `字`, `广告任务` before `广告`, `地区字符串` before `地区`,
  and `宏参数` before `参数`.

Wrong:

```python
_UNIT_RE = re.compile(r"(?P<unit>个|条|字|字符|广告|广告任务)")
```

This parses `100字符` as `100字` and `10广告任务` as `10广告`.

Correct:

```python
_UNIT_RE = re.compile(r"(?P<unit>(?:个|条)?(?:字符|字|广告任务|广告)|个|条)")
```

Then normalize semantic equivalents in one function, such as mapping `区县`,
`地区字符串`, and `地区` to `地区`.

---

## Testing Requirements

<!-- What level of testing is expected -->

For deterministic PRD facts parsers:

- Add a parser-level unit test for every new fact shape.
- Add a regression for the false-positive / false-negative that motivated the
  rule.
- Include at least one negative case showing the guard does not punish a valid
  boundary/error test. Example anchors:
  `tests/testcase_generator/test_prd_facts.py:73`,
  `tests/testcase_generator/test_prd_facts.py:80`,
  `tests/testcase_generator/test_prd_facts.py:88`.

---

## Code Review Checklist

<!-- What reviewers should check -->

(To be filled by the team)
