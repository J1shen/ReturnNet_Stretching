import torch
import torch.nn as nn
import torch.nn.functional as F
import tqdm
from scheduler import linear_beta_schedule
from util import img2vec,vec2img
from model import Unet

class DiffusionModel():
    def __init__(self,
                 timesteps = 200
                 ):
        self.timesteps = timesteps
 
        # define beta schedule
        self.betas = linear_beta_schedule(timesteps=timesteps)
 
        # define alphas 
        self.alphas = 1. - self.betas
        self.alphas_cumprod = torch.cumprod(self.alphas, axis=0)
        self.alphas_cumprod_prev = F.pad(self.alphas_cumprod[:-1], (1, 0), value=1.0)
        self.sqrt_recip_alphas = torch.sqrt(1.0 / self.alphas)
        
        # calculations for diffusion q(x_t | x_{t-1}) and others
        self.sqrt_alphas_cumprod = torch.sqrt(self.alphas_cumprod)
        self.sqrt_one_minus_alphas_cumprod = torch.sqrt(1. - self.alphas_cumprod)
        
        # calculations for posterior q(x_{t-1} | x_t, x_0)
        self.posterior_variance = self.betas * (1. - self.alphas_cumprod_prev) / (1. - self.alphas_cumprod)

        #training

    def extract(self,a, t, x_shape):
        batch_size = t.shape[0]
        out = a.gather(-1, t.cpu())
        return out.reshape(batch_size, *((1,) * (len(x_shape) - 1))).to(t.device)
    
    # forward diffusion (using the nice property)
    def q_sample(self,x_start, t, noise=None):
        if noise is None:
            noise = torch.randn_like(x_start)
    
        sqrt_alphas_cumprod_t = self.extract(self.sqrt_alphas_cumprod, t, x_start.shape)
        sqrt_one_minus_alphas_cumprod_t = self.extract(
            self.sqrt_one_minus_alphas_cumprod, t, x_start.shape
        )
    
        return sqrt_alphas_cumprod_t * x_start + sqrt_one_minus_alphas_cumprod_t * noise
    
    def get_noisy_image(self,x_start, t):
        # add noise
        print(t)
        x_noisy = self.q_sample(x_start, t=t)
        
        # turn back into PIL image
        noisy_image = vec2img(x_noisy)
        return noisy_image
    
    def p_losses(self,denoise_model, x_start, t, noise=None, loss_type="l1"):
        # 先采样噪声
        if noise is None:
            noise = torch.randn_like(x_start)
        
        # 用采样得到的噪声去加噪图片
        x_noisy = self.q_sample(x_start=x_start, t=t, noise=noise)
        predicted_noise = denoise_model(x_noisy, t)
        
        # 根据加噪了的图片去预测采样的噪声
        if loss_type == 'l1':
            loss = F.l1_loss(noise, predicted_noise)
        elif loss_type == 'l2':
            loss = F.mse_loss(noise, predicted_noise)
        elif loss_type == "huber":
            loss = F.smooth_l1_loss(noise, predicted_noise)
        else:
            raise NotImplementedError()
    
        return loss

    @torch.no_grad()
    def p_sample(self,model, x, t, t_index):
        betas_t = self.extract(self.betas, t, x.shape)
        sqrt_one_minus_alphas_cumprod_t = self.extract(
            self.sqrt_one_minus_alphas_cumprod, t, x.shape
        )
        sqrt_recip_alphas_t = self.extract(self.sqrt_recip_alphas, t, x.shape)
        
        # Equation 11 in the paper
        # Use our model (noise predictor) to predict the mean
        model_mean = sqrt_recip_alphas_t * (
            x - betas_t * model(x, t) / sqrt_one_minus_alphas_cumprod_t
        )
    
        if t_index == 0:
            return model_mean
        else:
            posterior_variance_t = self.extract(self.posterior_variance, t, x.shape)
            noise = torch.randn_like(x)
            # Algorithm 2 line 4:
            return model_mean + torch.sqrt(posterior_variance_t) * noise 
    
    # Algorithm 2 (including returning all images)
    @torch.no_grad()
    def p_sample_loop(self,model, shape):
        device = next(model.parameters()).device
    
        b = shape[0]
        # start from pure noise (for each example in the batch)
        img = torch.randn(shape, device=device)
        imgs = []
    
        for i in tqdm(reversed(range(0, self.timesteps)), desc='sampling loop time step', total=self.timesteps):
            img = self.p_sample(model, img, torch.full((b,), i, device=device, dtype=torch.long), i)
            imgs.append(img.cpu().numpy())
        return imgs
    
    @torch.no_grad()
    def sample(self,model, image_size, batch_size=16, channels=3):
        return self.p_sample_loop(model, shape=(batch_size, channels, image_size, image_size))
    
    def train(self,dataloader,epochs=1):
        device = "cuda" if torch.cuda.is_available() else "cpu"
        model = Unet(
            dim=28,
            channels=1,
            dim_mults=(1, 2, 4,)
        )
        optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
        for epoch in range(epochs):
            for step, batch in enumerate(dataloader):
                optimizer.zero_grad()
        
                batch_size = batch["pixel_values"].shape[0]
                batch = batch["pixel_values"].to(device)
        
                # Algorithm 1 line 3: sample t uniformally for every example in the batch
                t = torch.randint(0, self.timesteps, (batch_size,), device=device).long()
            
                loss = self.p_losses(model, batch, t, loss_type="huber")
            
                if step % 100 == 0:
                    print("Loss:", loss.item())
            
                loss.backward()
                optimizer.step()

        return model
    
    def inference(self,model,image_size=28,channels=1):
        # sample 64 images
        samples = self.sample(model, image_size=image_size, batch_size=64, channels=channels)
        
        # show a random one
        random_index = 5