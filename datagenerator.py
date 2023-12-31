from torch.utils.data import DataLoader
from datasets import load_dataset,Dataset,DatasetDict
from util import pil2tensor
from ultralytics import YOLO
from PIL import Image
import random,torch

model_det = YOLO("yolov8x.pt")
model_pose = YOLO("yolov8x-pose-p6.pt")  # load a pretrained model (recommended for training)

def paste_image_centered(image, new_size=224):
    # 计算缩放比例
    width, height = image.size
    max_size = max(width, height)
    if max_size > new_size:
      scale = new_size / max_size
      width = round(width * scale)
      height = round(height * scale)
    # 创建新图像
    new_image = Image.new("RGB", (new_size, new_size), (255, 255, 255))
    # 粘贴原图像
    x = (new_size - width) // 2
    y = (new_size - height) // 2
    new_image.paste(image.resize((width, height)), (x, y))
    # 返回新图像
    return new_image

def flatten_and_pad(tensor, max_len=32):
    """
    将一个tensor展平成一维向量，并截取前x个，不足则补零
    """
    flattened = tensor.reshape(-1)
    if flattened.size(0) >= max_len:
        return flattened[:max_len]
    else:
        padded = torch.zeros(max_len)
        padded[:flattened.size(0)] = flattened
        return padded

def generate_data(example):
  image = example['image']
  detected = model_det(image)
  boxes = detected[0].boxes.xyxy.numpy()
  if boxes.size == 0:
     return example
  offset = 10
  person = image.crop((boxes[0][0]-offset, boxes[0][1]-offset, boxes[0][2]+offset, boxes[0][3]+offset))
  new_img = paste_image_centered(person)
  example['image_ori'] = pil2tensor(new_img)

  pose = model_pose(new_img)
  example['keys_ori'] = flatten_and_pad(pose[0].keypoints.xy[0])

  size_ori = new_img.size
  ratio_w = random.uniform(0.9, 1)
  ratio_h = random.uniform(1, 1.2)
  new_size = (int(size_ori[0]*ratio_w), int(size_ori[1]*ratio_h))
  trans_img = image.resize(new_size)
  new_img2 = paste_image_centered(trans_img)

  example['image_trans'] = pil2tensor(new_img2)
  pose2 = model_pose(new_img2 )
  example['keys_trans'] = flatten_and_pad(pose2[0].keypoints.xy[0])
  return example
  
def create_dataset(upload=False):
  dataset = load_dataset("fuliucansheng/pascal_voc", "voc2012_main")
  person_dataset = dataset.filter(lambda example: example['objects']['classes'] == [ 14 ])
  #person_dataset = dataset.filter(lambda example: example['classes'] == [ 14 ])
  train_dataset = Dataset.from_dict({'image': person_dataset['train']['image']}) # 仅保留'image'列
  val_dataset = Dataset.from_dict({'image': person_dataset['validation']['image']}) # 仅保留'image'列

  train_dataset = train_dataset.map(generate_data)
  val_dataset = val_dataset.map(generate_data)
  
  train_loader = DataLoader(train_dataset)
  val_loader = DataLoader(val_dataset)
  if upload :
    new_data = DatasetDict({'train':train_dataset,'validation':val_dataset})

  return train_loader,val_loader


if __name__ == '__main__':
  pass

'''
def crop_image(image, center, crop_size):
    left = max(0, center[0] - crop_size[0] // 2)
    right = min(image.size[0], center[0] + crop_size[0] // 2)
    top = max(0, center[1] - crop_size[1] // 2)
    bottom = min(image.size[1], center[1] + crop_size[1] // 2)
    return image.crop((left, top, right, bottom))

def generate_data(example):
  img_size = (256,256)
  image = example['image'].resize(img_size)
  example['image_ori'] = image

  detect = model_det(image)
  pose = model_pose(image)
  example['keys_ori'] = pose[0].keypoints.xy[0]

  ratio_w = random.uniform(0.9, 1)
  ratio_h = random.uniform(1, 1.2)
  new_size = (int(256*ratio_w), int(256*ratio_h))
  new_img = image.resize(new_size)

  boxes = detect[0].boxes.xyxy.numpy()
  center = (boxes[0][0] + boxes[0][2]) // 2, (boxes[0][1] + boxes[0][3]) // 2  # extract center point from box
  corped = crop_image(new_img, center, img_size).resize(img_size)

  example['image_trans'] = corped #np.asarray(corped)
  pose2 = model_pose(corped)
  example['keys_trans'] = pose2[0].keypoints.xy[0]
  return example
  '''