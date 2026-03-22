# AppSheet 数式クイックリファレンス — コピペ用

AppSheet設定画面で直接コピペできる数式集です。

---

## Step1: Security Filter

**場所:** Security > Security Filters > 日報テーブル > Filter condition

```
OR(USERROLE() = "Admin", [メールアドレス] = USEREMAIL())
```

---

## Step2-1: 上長コメント 編集制限

**場所:** Data > Columns > 上長コメント > Update Behavior > Editable?

```
USERROLE() = "Admin"
```

---

## Step2-2: 上長コメント 表示制限（オプション）

**場所:** Data > Columns > 上長コメント > Show?

```
OR(USERROLE() = "Admin", ISNOTBLANK([上長コメント]))
```

---

## Step3: Automation Bot Trigger条件

**場所:** Automation > Bot > Trigger > Condition

```
AND(ISNOTBLANK([上長コメント]), [_THISROW_BEFORE].[上長コメント] <> [_THISROW_AFTER].[上長コメント])
```

---

## Step3: 通知設定

**場所:** Automation > Bot > Step > Send notification / Send email

| 項目 | 値 |
|------|-----|
| To | `[メールアドレス]` |
| Title | `上長からコメントが届きました` |
| Body | `[上長コメント]` |

---

## Step4: 管理画面 表示制限

**場所:** App > Views > 管理用一覧 > Display > Show if

```
USERROLE() = "Admin"
```
