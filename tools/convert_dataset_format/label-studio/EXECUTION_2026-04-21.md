# Label Studio 数据集流水线执行记录

- 执行日期：`2026-04-21`
- 执行脚本：[run_label_studio_delivery_pipeline.py](/Users/dingliantao/codes/image-video-data-annotation-tool/tools/convert_dataset_format/label-studio/run_label_studio_delivery_pipeline.py)
- 允许导出的标签：`fallen_tree`、`diseased_tree`
- 压缩格式：`zip`

## Project 1

输入导出文件：
`datas/label-studio-export/tree-damage/project-1-at-2026-04-17-02-34-c1ad62c4.json`

Upload 图片根目录：`~/DockerDatas/label-studio/mydata/media/upload/1`

执行命令：

```bash
uv run python tools/convert_dataset_format/label-studio/run_label_studio_delivery_pipeline.py \
  --input datas/label-studio-export/tree-damage/project-1-at-2026-04-17-02-34-c1ad62c4.json \
  --source-image-root outputs/0901/damage_tiles \
  --upload-image-root ~/DockerDatas/label-studio/mydata/media/upload/1 \
  --subset-root outputs/0901/label_studio_delivery_pipeline_2026-04-21 \
  --allowed-label fallen_tree \
  --allowed-label diseased_tree \
  --archive-format zip
```

输出结果：

- `outputs/0901/label_studio_delivery_pipeline_2026-04-21`
- `outputs/0901/label_studio_delivery_pipeline_2026-04-21.zip`

统计数据：

- 图片数量：`3615`
- 标注图片数量：`131`
- 子集导出图片数量：`131`
- 正样本导出图片数量：`67`
- 空标注图片数量：`64`
- 最后导出的图片数量：`131`
- 各个类型的数量：
  - `diseased_tree`：`52`
  - `fallen_tree`：`15`

## Project 5

输入导出文件：
`datas/label-studio-export/tree-damage/project-5-at-2026-04-17-02-35-b543b5b9.json`

Upload 图片根目录：`~/DockerDatas/label-studio/mydata/media/upload/2`

执行命令：

```bash
uv run python tools/convert_dataset_format/label-studio/run_label_studio_delivery_pipeline.py \
  --input datas/label-studio-export/tree-damage/project-5-at-2026-04-17-02-35-b543b5b9.json \
  --source-image-root outputs/0910/damage_tiles \
  --upload-image-root ~/DockerDatas/label-studio/mydata/media/upload/2 \
  --subset-root outputs/0910/label_studio_delivery_pipeline_2026-04-21 \
  --allowed-label fallen_tree \
  --allowed-label diseased_tree \
  --archive-format zip
```

输出结果：

- `outputs/0910/label_studio_delivery_pipeline_2026-04-21`
- `outputs/0910/label_studio_delivery_pipeline_2026-04-21.zip`

统计数据：

- 图片数量：`3654`
- 标注图片数量：`26`
- 子集导出图片数量：`26`
- 正样本导出图片数量：`25`
- 空标注图片数量：`1`
- 最后导出的图片数量：`26`
- 各个类型的数量：
  - `diseased_tree`：`22`
  - `fallen_tree`：`5`
