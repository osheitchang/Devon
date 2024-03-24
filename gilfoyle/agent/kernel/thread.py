import os

from gilfoyle.agent.evaluate import evaluate
from gilfoyle.agent.tools.unified_diff.create_diff import generate_unified_diff
from gilfoyle.agent.tools.unified_diff.prompts.udiff_prompts import UnifiedDiffPrompts
from gilfoyle.agent.tools.unified_diff.utils import apply_diff_to_file_map
from sandbox.shell import Shell
from gilfoyle.sandbox.traverse import glob_repo_code
from gilfoyle.format import reformat_code
from gilfoyle.agent.reasoning.reason import ReasoningPrompts
from agent.evaluate.evaluate import EvaluatePrompts
from anthropic import Anthropic
from gilfoyle.agent.clients.client import ClaudeOpus, Message
import json
import traceback

class Thread:
    def __init__(self, repo_url: str, task: str):
        self.repo_url = repo_url
        self.task = task
        api_key=os.environ.get("ANTHROPIC_API_KEY")

        self.reasoning_model = ClaudeOpus(api_key=api_key, system_message=ReasoningPrompts.system, max_tokens=1024)
        self.diff_model = ClaudeOpus(api_key=api_key, system_message=UnifiedDiffPrompts.main_system + UnifiedDiffPrompts.system_reminder, max_tokens=4096)
        self.critic = ClaudeOpus(api_key=api_key, system_message=EvaluatePrompts.system, max_tokens=1024)

    def run(self):
        with Shell(repo_url=self.repo_url) as shell:
            success = False
            failure_context = []
            while not success:
                repo_data = glob_repo_code(shell)

                ast_data = {path: data.code for path, data in repo_data.items()}

                print("Reasoning")
                r2 = self.reasoning_model.chat([
                    Message(role="user", content=ReasoningPrompts.user_msg(goal=self.task, code=json.dumps(ast_data)))
                ])

                code_w_line_numbers = {path: data.code_with_lines for path, data in repo_data.items()}
                print("Fixing code")

                try:
                    out = generate_unified_diff(client=self.diff_model, original_code=json.dumps(code_w_line_numbers), input=r2, failure_context=failure_context)
                except Exception as e:
                    error = traceback.format_exc()
                    print(error)
                    failure_context.append(error)
                    continue

                file_code_mapping = {path: data.code for path, data in repo_data.items()}

                print("Applying diffs")
                new, touched_files = apply_diff_to_file_map(file_code_mapping=file_code_mapping, diff=out)
                formatted_new = {path: reformat_code(code) for path, code in new.items()}
                print(formatted_new)

                for file in touched_files:
                    print(f"{file}:\n\n {json.dumps(formatted_new[file])}\n\n")

                print("Evaluating code")
                eval = self.critic.chat(messages=[
                    Message(
                        role="user",
                        content=EvaluatePrompts.user_msg(goal=self.task, requirements=r2, old_code=json.dumps(file_code_mapping), new_code=json.dumps(formatted_new))
                    )
                ])
                print(eval)
                success = True