# SkillShift: Source Balanced Feedback for Reliable Agent Skill Evolution

CSE 572: Data Mining (Fall 2026), Group 5.

An agent that updates its skill from past attempts can treat repeated failures as stronger evidence than they really are. If twenty failed attempts all come from one broken workbook, the optimizer reads that as twenty reasons to change the skill, and the new rule can then hurt many other tasks. We check whether feedback selection should look at where each attempt came from, not only how similar it is to other attempts: repeated failures from one source count once, while the same failure across different tasks still counts as strong evidence.

We add feedback selection before SkillOpt's reflection step and compare five methods on 120 SpreadsheetBench Verified tasks: unfiltered feedback, exact deduplication, semantic deduplication, source balancing alone, and our method, which groups records by source family and failure behavior. Everything else (executor, optimizer, starting skill, prompt and token budget) stays the same across methods.

Team: Vemula Thushar Reddy, Charith Kutikuppala, Venkata Pradeep Reddy Venuthurla, Varshini Akula, Thanishka Bolisetty.
