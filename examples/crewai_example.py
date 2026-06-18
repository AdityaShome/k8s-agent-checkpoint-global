#!/usr/bin/env python3
"""
Drop-in checkpoint usage with CrewAI.

This example shows how to wrap CrewAI task execution with agent-checkpoint
so that a long multi-task crew can resume after a pod restart without
re-running completed tasks.

Install: pip install crewai agent-checkpoint
"""

# from crewai import Agent, Task, Crew
# from checkpoint import CheckpointStore, checkpoint
# import os
#
# store = CheckpointStore(os.getenv("CHECKPOINT_DB", "sqlite:///crewai_run.db"))
# RUN_ID = os.getenv("RUN_ID", "crewai-run-001")
#
# researcher = Agent(
#     role="Researcher",
#     goal="Research the given topic thoroughly",
#     backstory="You are an expert researcher with access to many sources.",
#     verbose=True,
# )
#
# writer = Agent(
#     role="Writer",
#     goal="Write a clear summary based on research",
#     backstory="You are a technical writer who distills complex topics.",
#     verbose=True,
# )
#
# TOPICS = ["kubernetes", "ebpf", "wasm", "service-mesh", "gitops"]
#
# for i, topic in enumerate(TOPICS):
#
#     # --- Step 1: research ---
#     with checkpoint(RUN_ID, f"research_{i:02d}", store) as ctx:
#         if ctx.result is not None:
#             research = ctx.result
#         else:
#             task = Task(
#                 description=f"Research the topic: {topic}",
#                 agent=researcher,
#                 expected_output="A structured set of key findings.",
#             )
#             crew = Crew(agents=[researcher], tasks=[task], verbose=False)
#             research = crew.kickoff()
#             ctx.result = str(research)
#
#     # --- Step 2: write summary ---
#     with checkpoint(RUN_ID, f"write_{i:02d}", store) as ctx:
#         if ctx.result is not None:
#             summary = ctx.result
#         else:
#             task = Task(
#                 description=f"Write a 3-paragraph summary of: {research}",
#                 agent=writer,
#                 expected_output="A clear 3-paragraph summary.",
#             )
#             crew = Crew(agents=[writer], tasks=[task], verbose=False)
#             summary = crew.kickoff()
#             ctx.result = str(summary)
#
#     print(f"[{i+1}/{len(TOPICS)}] {topic}: done")
#
# print("All topics processed.")
