import torch
from torch.utils.tensorboard import SummaryWriter
import yaml
from ddsp.model import DDSP, DDSP_noseq
from effortless_config import Config
from os import path
from preprocess import Dataset
from tqdm import tqdm
from ddsp.core import multiscale_fft, safe_log, mean_std_loudness
import soundfile as sf
from einops import rearrange
from ddsp.utils import get_scheduler
import numpy as np


def train(model,epochs,dataloader,writer,opt):
    best_loss = float("inf")
    mean_loss = 0
    n_element = 0
    step = 0
    # tqdm is a loading bar
    for e in tqdm(range(epochs)):
        # sound pitch loudness
        for s, p, l in dataloader:
            s = s.to(device)
            p = p.unsqueeze(-1).to(device)
            l = l.unsqueeze(-1).to(device)
            # s torch.Size([16, 64000]) - p torch.Size([16, 400, 1]) - l torch.Size([16, 400, 1])
            l = (l - mean_loudness) / std_loudness

            y,h,n = model(p, l)
            y = y.squeeze(-1)

            ori_stft = multiscale_fft(
                s,
                config["train"]["scales"],
                config["train"]["overlap"],
            )
            rec_stft = multiscale_fft(
                y,
                config["train"]["scales"],
                config["train"]["overlap"],
            )

            loss = 0
            for s_x, s_y in zip(ori_stft, rec_stft):
                lin_loss = (s_x - s_y).abs().mean()
                log_loss = (safe_log(s_x) - safe_log(s_y)).abs().mean()
                loss = loss + lin_loss + log_loss

            opt.zero_grad()
            loss.backward()
            opt.step()

            writer.add_scalar("loss", loss.item(), step)

            step += 1

            n_element += 1
            mean_loss += (loss.item() - mean_loss) / n_element

        if not e % 10:
            writer.add_scalar("lr", schedule(e), e)
            writer.add_scalar("reverb_decay", model.reverb.decay.item(), e)
            writer.add_scalar("reverb_wet", model.reverb.wet.item(), e)
            # scheduler.step()
            if mean_loss < best_loss:
                best_loss = mean_loss
                torch.save(
                    model.state_dict(),
                    path.join(args.ROOT, args.NAME, "state.pth"),
                )

            mean_loss = 0
            n_element = 0

            audio = torch.cat([s, y], -1).reshape(-1).detach().cpu().numpy()

            sf.write(
                path.join(args.ROOT, args.NAME, f"eval_{e:06d}.wav"),
                audio,
                config["preprocess"]["sampling_rate"],
            )


def test(model,dataloader):
    best_loss = float("inf")
    mean_loss = 0
    n_element = 0
    
    model.load_state_dict(torch.load(path.join(args.ROOT, args.NAME, "state.pth")))
    model.eval()
    # sound pitch loudness
    for s, p, l in dataloader:
        with torch.no_grad():
            s = s.to(device)
            p = p.unsqueeze(-1).to(device)
            l = l.unsqueeze(-1).to(device)
            # s torch.Size([16, 64000]) - p torch.Size([16, 400, 1]) - l torch.Size([16, 400, 1])
            l = (l - mean_loudness) / std_loudness

            y,h,n = model(p, l)
            y = y.squeeze(-1)
            h = h.squeeze(-1)
            n = n.squeeze(-1)

            n_element += 1

            
            ref = s.reshape(-1).detach().cpu().numpy()
            synth = y.reshape(-1).detach().cpu().numpy()
            harmonic = h.reshape(-1).detach().cpu().numpy()
            noise = n.reshape(-1).detach().cpu().numpy()

            sf.write(
                path.join(args.ROOT, args.NAME, f"test_ref.wav"),
                ref,
                config["preprocess"]["sampling_rate"],
            )
            sf.write(
                path.join(args.ROOT, args.NAME, f"test_synth.wav"),
                synth,
                config["preprocess"]["sampling_rate"],
            )
            sf.write(
                path.join(args.ROOT, args.NAME, f"test_synth_harmonic.wav"),
                harmonic,
                config["preprocess"]["sampling_rate"],
            )
            sf.write(
                path.join(args.ROOT, args.NAME, f"test_synth_noise.wav"),
                noise,
                config["preprocess"]["sampling_rate"],
            )
        break

def transfer(model,dataloader):
    best_loss = float("inf")
    mean_loss = 0
    n_element = 0
    
    model.load_state_dict(torch.load(path.join(args.ROOT, "debug", "state.pth")))
    model.eval()
    # sound pitch loudness
    for s, p, l in dataloader:
        with torch.no_grad():
            s = s.to(device)
            p = p.unsqueeze(-1).to(device)
            l = l.unsqueeze(-1).to(device)
            # s torch.Size([16, 64000]) - p torch.Size([16, 400, 1]) - l torch.Size([16, 400, 1])
            l = (l - mean_loudness) / std_loudness

            y,h,n = model(p, l)
            y = y.squeeze(-1)
            h = h.squeeze(-1)
            n = n.squeeze(-1)

            n_element += 1

            
            ref = s.reshape(-1).detach().cpu().numpy()
            synth = y.reshape(-1).detach().cpu().numpy()
            harmonic = h.reshape(-1).detach().cpu().numpy()
            noise = n.reshape(-1).detach().cpu().numpy()

            sf.write(
                path.join(args.ROOT, args.NAME, f"test_ref.wav"),
                ref,
                config["preprocess"]["sampling_rate"],
            )
            sf.write(
                path.join(args.ROOT, args.NAME, f"test_synth.wav"),
                synth,
                config["preprocess"]["sampling_rate"],
            )
            sf.write(
                path.join(args.ROOT, args.NAME, f"test_synth_harmonic.wav"),
                harmonic,
                config["preprocess"]["sampling_rate"],
            )
            sf.write(
                path.join(args.ROOT, args.NAME, f"test_synth_noise.wav"),
                noise,
                config["preprocess"]["sampling_rate"],
            )
        break

class args(Config):
    CONFIG = "config.yaml"
    NAME = "long_training"
    ROOT = "runs"
    STEPS = 500000
    BATCH = 16
    START_LR = 1e-3
    STOP_LR = 1e-4
    DECAY_OVER = 400000
    MODE = "train"


args.parse_args()

with open(args.CONFIG, "r") as config:
    config = yaml.safe_load(config)

device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")

if config["train"]["sequential"] == True:
    model = DDSP(**config["model"]).to(device)
else:
    model = DDSP_noseq(**config["model"]).to(device)

print("Called model: \n {}".format(model))
dataset = Dataset(config["preprocess"]["out_dir"])

if args.MODE == "train":
    shuffle = True
else:
    shuffle = False

dataloader = torch.utils.data.DataLoader(
    dataset,
    args.BATCH,
    shuffle,
    drop_last=True,
)

mean_loudness, std_loudness = mean_std_loudness(dataloader)
config["data"]["mean_loudness"] = mean_loudness
config["data"]["std_loudness"] = std_loudness

writer = SummaryWriter(path.join(args.ROOT, args.NAME), flush_secs=20)

with open(path.join(args.ROOT, args.NAME, "config.yaml"), "w") as out_config:
    yaml.safe_dump(config, out_config)

opt = torch.optim.Adam(model.parameters(), lr=args.START_LR)

schedule = get_scheduler(
    len(dataloader),
    args.START_LR,
    args.STOP_LR,
    args.DECAY_OVER,
)

# scheduler = torch.optim.lr_scheduler.LambdaLR(opt, schedule)

epochs = int(np.ceil(args.STEPS / len(dataloader)))

if args.MODE == "train":
    train(model,epochs,dataloader,writer,opt)
elif args.MODE == "test":
    test(model,dataloader)
elif args.MODE == "transfer":
    transfer(model,dataloader)