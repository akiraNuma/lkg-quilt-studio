# Codex のプロジェクト入口

作業前に [CLAUDE.md](CLAUDE.md) と `.claude/rules/documentation.md` を読む。
運用・検証フロー・設計判断の正本はこれらのファイルとする。
このファイルには Codex からの読み込み手順だけを置く。

## 作業対象に応じて読むルール

共通 hook が常時ルールと `paths:` の一致するルールを渡す。
hook が未信頼・無効なら、以下の参照先を自分で読む。
ルートから作業するときも、編集前に対象のルールを読む。

| 作業対象 | 読むファイル |
| --- | --- |
| `viewer/` | `.claude/rules/viewer-vue.md` |
| `converter/` | `.claude/rules/converter-python.md` |
| Looking Glass の仕様・モデル・外部 API | `.claude/rules/external-apis.md` |

## スキルとレビュー

- `.agents/skills/` は `.claude/skills/` への相対リンクとする。
  手順の正本をコピーして二重管理しない。
- コード変更後は `CLAUDE.md` の機械チェックを通す。
  続いて `.agents/skills/review-loop/SKILL.md` を読み、レビューを実行する。
- ハーネス変更時は `.agents/skills/harness-audit/SKILL.md` を読む。
  今回変更した入口・参照・設定を対象に整合性を確認する。
- Codex のレビュー担当は `.codex/agents/code_reviewer.toml`。
  名前付き担当を選べない環境では、通常のサブエージェントに
  `.claude/agents/code-reviewer.md` を読ませ、読み取り専用でレビューさせる。

権限と hook の正本は `.claude/settings.json`。
`python3 scripts/sync-harness.py` で Codex 用の機械設定を生成する。
`scripts/check-harness.sh` で同期・参照・入力形式を検証する。
実行権限モードと hook の信頼設定は、クライアント側の設定に従う。
