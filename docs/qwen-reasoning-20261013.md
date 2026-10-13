# Explicit Qwen reasoning continuation

The user requested a new Task059 continuation with xhigh, falling back to high
only if xhigh is unavailable. Qwen3.8-max's official Chat Completions contract
supports low, medium and xhigh; high/max map to xhigh, minimal maps to low, and
none disables thinking. This run uses the native xhigh value.

Source: https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions/

The historical qwen-native-16k profile remains disabled. A new explicit
qwen-native-xhigh-16k profile sends enable_thinking=true, reasoning_effort=xhigh
and preserve_thinking=true. It does not send the mutually exclusive
thinking_budget. The shared native loop already retains the original assistant
reasoning_content field separately, counts it against context admission, and
drops only whole old turns. It never copies reasoning into public content.

The new recovery flag --qwen-reasoning-effort xhigh is limited to the same
Qwen UI-KOBE-like Task059 checkpoint. The frozen migration records the exact
tag, old profile and new profile, accepts only implementation-defined profiles,
and preserves the CUA contract, original native history/IDs, command count and
cumulative decision limit. The checkpoint files are not rewritten. New
checkpoints record the new profile normally. Other actor profiles reject a
generation mismatch.

The model, endpoint, six-attempt retry policy, 16,000-token request cap,
32,000-token actor pool, two semantic repairs, deadlines and Docker VM remain
unchanged. Local validation proves the wire contract and checkpoint migration;
only an actual provider response can establish gateway compatibility. A
successful configured request does not prove the server used the requested
internal reasoning budget. No hidden reasoning transcript is a task result.
