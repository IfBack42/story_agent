# WAI Illustrious v15 通用提示词使用指南（Forge）

> 适用环境：Stable Diffusion WebUI Forge + WAI Illustrious v15 / Illustrious 系模型
>
> 目标：让其他 AI、Agent 或用户快速理解该模型的提示词组织方式、常用参数、Negative Prompt 和 ControlNet / OpenPose 配合方法。
>
> 本版本仅面向普通二次元角色、剧情插图、场景插画与姿势控制，不包含成人向或色情内容。

## 1. 模型特点

WAI Illustrious v15 属于 Illustrious / SDXL 系二次元模型，适合：

- 二次元人物
- 单人或多人角色图
- 剧情插图
- 日常、校园、奇幻、科幻、战斗等场景
- 标签式（Danbooru 风格）提示词
- 明确的人体姿势、镜头和场景
- 与 OpenPose / ControlNet 联用

该模型更适合 **短而明确的 tag prompt**，不推荐把提示词写成很长的自然语言散文。

核心原则：

1. 先写主体数量与角色类型
2. 再写角色身份与核心外观
3. 再写姿势与镜头
4. 最后写场景、光影和风格
5. 不要堆大量同义词
6. 某个结构反复出错时，优先用 Negative Prompt 或 ControlNet，而不是继续堆更多描述词
7. 重要概念尽量放在提示词前部

## 2. 推荐提示词结构

推荐结构：

```text
[质量]
[主体]
[角色身份]
[核心外观]
[姿势 / 动作]
[镜头]
[场景]
[光影 / 风格]
```

标准人物模板：

```text
masterpiece, best quality,
1girl, solo,
[character],
[hair],
[eyes],
[clothing],
[distinctive features],
[pose or action],
[camera / composition],
[scene],
[lighting],
anime style
```

男性角色模板：

```text
masterpiece, best quality,
1boy, solo,
[character],
[hair],
[eyes],
[clothing],
[distinctive features],
[pose or action],
[camera / composition],
[scene],
[lighting],
anime style
```

如果主体不是人物，可使用：

```text
masterpiece, best quality,
[main subject],
[important appearance],
[action if any],
[camera / composition],
[scene],
[lighting],
anime illustration
```

## 3. Prompt 长度建议

不要追求越长越好。

推荐：

- 普通角色：20～40 个左右有效 tag
- 复杂角色 / 场景：40～70 个有效 tag
- 超过这个范围后，容易出现注意力稀释

优先级建议：

```text
主体 > 角色身份 > 核心外观 > 动作 / 姿势 > 镜头 > 场景 > 装饰细节
```

重要概念应尽量靠前。

## 4. 单人角色模板

```text
masterpiece, best quality,
1girl, solo,
[character],
[hair],
[eyes],
[clothing],
[body type if relevant],
full body,
front view,
[pose],
[scene],
[lighting],
anime style
```

常用 Negative Prompt：

```text
multiple people, duplicate,
back view, side view,
cropped, out of frame,
extra limbs, fused limbs,
bad anatomy, bad hands,
text, watermark, signature
```

## 5. 多人角色模板

如果确实需要两人或多人，应明确人数与关系。

例如双人：

```text
masterpiece, best quality,
2girls,
[character A],
[character B],
standing together,
[interaction],
[scene],
[lighting],
anime style
```

不要同时写：

```text
1girl, solo, 2girls
```

否则模型可能发生主体冲突。

多人场景中建议减少过多身体细节，把重点放在：

```text
人物数量
角色区分
站位 / 互动
场景
构图
```

## 6. 正面视角模板

如果希望人物正面：

```text
front view,
directly facing viewer,
facing viewer,
symmetrical frontal composition
```

Negative：

```text
back view,
rear view,
from behind,
side view,
turned away
```

如果仍然不稳定，优先使用 OpenPose。

## 7. 姿势控制：Prompt 与 OpenPose 的分工

当使用 OpenPose 时：

- **OpenPose 负责姿势与骨架**
- **Prompt 负责角色、外观、服装、场景、光影和风格**

不要在 Prompt 中重复写过多具体关节位置。

例如已有正面坐姿骨架时，Prompt 可以简化为：

```text
masterpiece, best quality,
1girl, solo,
long silver hair,
blue eyes,
white dress,
full body,
front view,
moonlit balcony,
soft blue lighting,
anime style
```

### OpenPose 推荐参数

```text
Preprocessor: openpose_full 或 dw_openpose_full
Pixel Perfect: ON
Control Weight: 0.8 ~ 0.95
Start: 0
End: 1
Control Mode: Balanced 或 ControlNet is more important
Use Mask: OFF
```

如果姿势跑偏：

```text
Weight → 0.9 ~ 1.0
```

如果人物太僵：

```text
Weight → 0.6 ~ 0.75
```

### 高层姿势语义不要全部删除

即使启用了 OpenPose，也可以保留：

```text
sitting
standing
lying
front view
full body
facing viewer
```

但应减少：

```text
left elbow raised,
right knee bent,
left hand on shoulder,
...
```

这类具体关节描述。

## 8. Forge 推荐基础参数

8GB 显存建议：

```text
Resolution: 768x1152 / 832x1216 / 1024x1024
Batch size: 1
Steps: 25~30
CFG: 5~6
Sampler: Euler a 或 DPM++ 2M Karras
Clip Skip: 2
VAE: Automatic
Hires.fix: OFF
```

如果加 ControlNet 后显存告警：

```text
GPU Weights: 5.5~6 GB
Batch size: 1
Hires.fix: OFF
一次只开 1 个 ControlNet
```

## 9. Negative Prompt 常用模块

Negative Prompt 应按当前任务选择，不建议每次全部堆满。

### 9.1 人体错误

```text
bad anatomy,
extra limbs,
missing limbs,
fused limbs,
extra fingers,
missing fingers,
bad hands,
bad feet,
deformed body
```

### 9.2 多人错误

单人任务时可加入：

```text
multiple people,
duplicate,
twins
```

女性单人：

```text
2girls
```

男性单人：

```text
2boys
```

### 9.3 构图错误

```text
cropped,
out of frame,
upper body only,
hidden legs,
back view,
side view
```

### 9.4 质量错误

```text
worst quality,
low quality,
blurry,
text,
watermark,
signature
```

### 9.5 服装或物件冲突

如果模型总是自动添加不需要的物件，应直接在 Negative 中排除。

例如不希望帽子：

```text
hat, cap, headwear
```

不希望武器：

```text
weapon, sword, gun
```

不要把所有可能的服饰和物件都加入 Negative，只添加当前场景确实需要排除的内容。

## 10. 不推荐的提示词写法

不推荐：

```text
beautiful, gorgeous, stunning, amazing, perfect,
very detailed, ultra detailed, super detailed,
awesome, incredible, fantastic
```

问题：

- 同义词过多
- 占用提示词注意力
- 对构图和角色没有实际帮助
- 容易挤压真正重要的角色和场景信息

更推荐：

```text
masterpiece, best quality,
1girl, solo,
silver hair, blue eyes,
black coat,
standing in rain,
night city,
anime style
```

## 11. 常见故障与修改方法

### A. 生成成两个人

正向：

```text
1girl, solo
```

负面：

```text
multiple people, duplicate
```

### B. 总是背面

正向：

```text
front view, facing viewer
```

负面：

```text
back view, rear view, side view
```

仍然失败时使用 OpenPose。

### C. 人物被裁切

正向：

```text
full body
```

负面：

```text
cropped, out of frame, upper body only
```

并使用更适合全身人物的竖图比例，例如：

```text
832x1216
```

### D. 手部容易出错

Negative：

```text
bad hands,
extra fingers,
missing fingers,
fused fingers
```

如果手部是画面重点，可考虑：

- 提高分辨率
- 使用 Inpaint
- 使用局部修复
- 选择手部无遮挡的 OpenPose 参考图

### E. Prompt 很长但模型不听话

优先删除：

```text
重复质量词
重复风格词
不重要的背景小物
大量同义形容词
```

保留：

```text
主体
角色
关键外观
动作
镜头
场景
光影
```

### F. OpenPose 与 Prompt 冲突

如果 Prompt 写：

```text
standing
```

而 OpenPose 是坐姿，模型可能产生冲突。

解决方式：

1. 以 OpenPose 为准时，修改 Prompt 的高层姿势词
2. 以 Prompt 为准时，更换 OpenPose 参考图
3. 不要让二者描述完全相反的姿势

## 12. 最小可用 Prompt

建议调试时先用最小 Prompt。

```text
masterpiece, best quality,
1girl, solo,
silver hair,
blue eyes,
white dress,
full body,
front view,
anime style
```

先确认：

- 单人正常
- 人脸正常
- 角色外观正确
- 构图正确
- 正面 / 全身正常

全部正常后，再逐步添加：

```text
pose
→ scene
→ lighting
→ atmosphere
→ detailed background
```

## 13. 正经剧情插图示例

### 13.1 雨夜城市

```text
masterpiece, best quality,
1girl, solo,
silver hair, blue eyes,
black coat,
standing under umbrella,
rainy city street,
night,
wet pavement,
neon reflections,
cinematic lighting,
melancholic expression,
anime style
```

Negative：

```text
multiple people, duplicate,
bad anatomy, extra limbs,
cropped, blurry,
text, watermark
```

### 13.2 奇幻战斗

```text
masterpiece, best quality,
1girl, solo,
female knight,
silver armor,
long red hair,
holding sword,
battle stance,
ruined castle,
burning battlefield,
smoke,
dramatic lighting,
anime style
```

Negative：

```text
multiple people, duplicate,
bad anatomy,
extra limbs,
bad hands,
cropped,
blurry,
text, watermark
```

### 13.3 校园日常

```text
masterpiece, best quality,
1girl, solo,
school uniform,
short black hair,
brown eyes,
sitting by classroom window,
afternoon,
sunlight,
quiet classroom,
gentle expression,
anime style
```

Negative：

```text
multiple people, duplicate,
bad anatomy,
cropped,
blurry,
text, watermark
```

### 13.4 情绪剧情

```text
masterpiece, best quality,
1girl, solo,
silver hair,
damaged armor,
holding broken sword,
standing on city wall,
looking into distance,
burning city,
night,
after rain,
wet stone,
smoke,
dramatic firelight,
melancholic expression,
anime style
```

## 14. 推荐工作流

```text
1. 先用短 Prompt 确认角色结构
2. 固定 Seed
3. 增加动作 / 姿势
4. 姿势不稳定 → OpenPose
5. 增加场景与光影
6. 再增加细节
7. 局部细节不足 → Inpaint
8. 最后再考虑 Hires.fix / Upscale
```

不要一开始同时堆：

```text
超长 Prompt
+ OpenPose
+ Depth
+ Hires.fix
+ 多个 LoRA
+ ADetailer
```

否则很难判断问题来自哪一步。

## 15. 给 Prompt Optimizer / Agent 的简短说明

如果需要让其他 AI 为该模型写 Prompt，可以直接使用：

> 我使用 WAI Illustrious v15（Illustrious/SDXL 系）在 Forge 中生成二次元角色与剧情插图。请使用简洁的英文 Danbooru/tag 风格提示词，不要写长篇自然语言。提示词顺序优先为：质量 → 主体 → 角色 → 核心外观 → 动作/姿势 → 镜头 → 场景 → 光影/风格。核心概念放前面，避免重复同义词。姿势复杂时优先交给 OpenPose，Prompt 不要重复描述每个关节。Negative Prompt 只针对当前任务的多人、错误视角、畸形肢体、裁切和低质量问题进行补充，不要无意义堆叠。

## 16. 给 Tool 的推荐 System Prompt

```text
You are a model-specific Stable Diffusion prompt optimizer.

Read the provided model guide and treat it as the primary source of prompting rules.

Preserve the user's intended subject, number of characters, scene, composition, and art style.

Rewrite prompts into concise English Danbooru-style tags.

Prefer the following order:
quality → subject → character → appearance → action/pose → camera/composition → scene → lighting/style.

Remove redundant synonyms and contradictory tags.

Do not make the prompt longer without a clear reason.

Build a targeted negative prompt based only on the current image and known failure modes.

If OpenPose is enabled, remove only detailed joint or limb-position descriptions that duplicate pose control.
Keep high-level pose and composition tags such as sitting, standing, lying, front view, full body, and facing viewer when they are part of the user's intent.

Do not invent a different subject, number of people, scene, art style, or composition.

Write changes and warnings in Chinese so the user can read them.
```

## 17. 总结

WAI Illustrious 提示词优化的核心不是“写得更多”，而是：

```text
主体明确
角色明确
动作明确
镜头明确
场景明确
减少冗余
针对性 Negative
复杂姿势交给 ControlNet
```

优先级：

```text
稳定性 > 堆叠细节
清晰结构 > 超长 Prompt
针对性 Negative > 万能 Negative
```
