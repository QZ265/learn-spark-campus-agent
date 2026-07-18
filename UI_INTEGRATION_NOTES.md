# UI 后端对接说明

本文只记录新版界面当前缺少的后端字段和接口。前端在字段缺失时展示真实空状态，不生成模拟记录。

## Dashboard 与学习计划

- 需要课表 CRUD 接口，字段：`id, user_id, course_id, course_name, weekday, start_time, end_time, location, teacher, color, repeat_rule`。
- 需要任务 CRUD 接口，字段：`id, user_id, course_id, title, type, date, time, status, reminder, notes, created_at, updated_at`。
- 需要 Dashboard 聚合接口返回今日课程、今日任务、未完成任务和本周到期项。
- 当前实现使用 `campus_lumina_plan_v1` 保存在当前浏览器，数据由用户真实创建，并非预置演示数据。

## 学生画像

- 当前 `/api/profile` 已支持课程画像的九个证据字段。
- 缺少独立的练习表现字段或练习记录查询接口；页面在没有 `source_type=practice` 的证据时显示“暂无练习记录”。
- 姓名、专业、年级目前来自本机账户设置；需要用户资料 API 后再与服务端同步。

## Agent 与资源

- `/api/resources/generate` 当前只接受 `user_id, request, course_id`，一次生成完整资源包。若要真正按单一类型生成，需要增加可选 `resource_types` 字段，同时保持现有字段兼容。
- 需要资源删除接口，例如 `DELETE /api/resources/<id>`；在接口提供前，删除按钮保持禁用。
- 收藏当前保存在 `campus_resource_favorites_v1`，需要收藏同步接口后才能跨设备使用。
- 资源记录缺少原始 `conversation_id`，因此资源中心暂时无法可靠“返回原始对话”。
- 缺少自建助手列表接口；当前页面只能操作本次创建或通过已知 ID 查询的助手。
- 最近使用 Agent 目前根据本机真实对话历史计算；跨设备同步需要会话列表接口返回 `course_id` 和 `updated_at`。

## 账户设置

- 基本资料、外观和回答偏好当前保存在 `campus_lumina_settings_v1`。
- 需要用户设置读写接口，建议保持 `profile, appearance, ai` 三个对象。
- AI 偏好尚未注入 `/api/chat`，避免在后端没有专用安全字段时将自定义指令静默拼接进用户问题。
