from dataclasses import dataclass
import torch
import torch.nn as nn
import torch.nn.functional as F
import math
import tiktoken
# 작은 것에서 큰 것을 만드는 것이 아니라
# 큰거에서 작은 것을 채워가자!
#--------------------------------------------------------------------------------------
class CausalSelfAttention(nn.Module):
    def __init__(self, config):
        super().__init__()
        assert config.n_embd % config.n_head ==0 
        self.c_attn = nn.Linear(config.n_embd, 3 * config.n_embd)
        self.c_proj = nn.Linear(config.n_embd, config.n_embd)
        self.n_head = config.n_head
        self.n_embd = config.n_embd

        self.register_buffer("bias", torch.tril(torch.ones(config.block_size, config.block_size))
                             .view(1,1,config.block_size,config.block_size))
    
    def forward(self,x):
        B, T ,C = x.size()
        qkv = self.c_attn(x)
        q, k , v = qkv.split(self.n_embd,dim=2)
        k = k.view(B, T, self.n_head, C//self.n_head).transpose(1,2) # (B,nh, T, hs)
        q = q.view(B, T, self.n_head, C//self.n_head).transpose(1,2) # (B,nh, T, hs)
        v = v.view(B, T, self.n_head, C//self.n_head).transpose(1,2) # (B,nh, T, hs)

        att = (q @ k.transpose(-2,-1)) * (1.0 / math.sqrt(k.size(-1)))
        att = att.masked_fill(self.bias[:,:,:T,:T] == 0, float("-inf"))
        att = F.softmax(att,dim=-1)
        y = att @ v #(B, nh, T, T) x (B, nb,T,hs) -> (B,nh,T,hs)
        y = y.transpose(1,2).contiguous().view(B,T,C)
        y = self.c_proj(y)
        return y




class MLP(nn.Module):

    def __init__(self, config):
        super().__init__()
        self.c_fc = nn.Linear(config.n_embd,4*config.n_embd)
        self.gelu = nn.GELU(approximate="tanh")
        self.c_proj = nn.Linear(4*config.n_embd , config.n_embd)
    
    def forward(self,x):
        x = self.c_fc(x)
        x = self.gelu(x)
        x = self.c_proj(x)

        return x


class Block(nn.Module):
    def __init__(self, config):
        super().__init__()
        self.ln_1 = nn.LayerNorm(config.n_embd)
        self.attn = CausalSelfAttention(config)
        self.ln_2 = nn.LayerNorm(config.n_embd)
        self.mlp = MLP(config)

    
    def forward(self,x):
        x = x + self.attn(self.ln_1(x))
        x = x + self.mlp(self.ln_2(x))
        return x
    ## gpt2 이후로 layernorm의 위치가 residual이 되기 전으로 변경 즉 입력초기 pre-LN


@dataclass
class GPTConfig:
    block_size :  int = 1024
    vocab_size : int = 50257 # number of tokens: 50,000 BPE merges + 256 bytes token + 1 <|endoftext|> token
    n_layer : int = 12
    n_head : int = 12
    n_embd: int = 768


class GPT(nn.Module):

    def __init__(self, config):
        super().__init__()
        self.config = config

        self.transformer = nn.ModuleDict(dict(
            wte = nn.Embedding(config.vocab_size, config.n_embd),
            wpe = nn.Embedding(config.block_size, config.n_embd),
            h = nn.ModuleList(Block(config) for _ in range(config.n_layer)),
            ln_f = nn.LayerNorm(config.n_embd),
        ))

        self.lm_head = nn.Linear(config.n_embd, config.vocab_size, bias=False)
    
    def forward(self,idx,targets=None):
        # idx is of shape(B,T)
        B, T = idx.size()
        assert T <= self.config.block_size, f"Cannot forward sequence of length {T}, block size is only {self.config.block_size}"
        pos = torch.arange(0,T, dtype=torch.long, device=idx.device) # shape {T}
        pos_emb = self.transformer.wpe(pos) # position embeddings of shape (T, n_embd)
        tok_emb = self.transformer.wte(idx) # token dembddings of shape(B,T,n_embd)
        x = tok_emb + pos_emb

        for block in self.transformer.h:
            x = block(x)
        
        x = self.transformer.ln_f(x)
        logits = self.lm_head(x) #(B, T, vocab_size)
        loss = None
        if targets is not None:
            loss = F.cross_entropy(logits.view(-1, logits.size(-1)), targets.view(-1))
        return logits, loss


    @classmethod
    def from_pretrained(cls, model_type):
        """Loads pretraiend GPT-2 Model weight from huggingface"""
        assert model_type in {'gpt2', 'gpt2-medium', 'gpt2-large','gpt2-xl'}
        from transformers import GPT2LMHeadModel
        print("loading weights from pretraiend gpt : %s" % model_type)

        config_args = {
            "gpt2": dict(n_layer=12, n_head=12, n_embd=768),
            "gpt2-medium" : dict(n_layer=24, n_head=16, n_embd=1024),
            "gpt2-large" : dict(n_layer=36, n_head=20, n_embd=1280),
            "gpt2-xl" : dict(n_layer=48, n_head=25, n_embd=1600),
        }[model_type]
        config_args["vocab_size"] = 50257
        config_args["block_size"] = 1024

        config = GPTConfig(**config_args)
        model = GPT(config)
        sd = model.state_dict()
        sd_keys = sd.keys()
        sd_keys = [k for k in sd_keys if not k.endswith('.attn.bias')]

        model_hf = GPT2LMHeadModel.from_pretrained(model_type)
        sd_hf = model_hf.state_dict()

        sd_keys_hf = sd_hf.keys()
        sd_keys_hf = [k for k in sd_keys_hf if not k.endswith('.attn.masked_bias')]
        sd_keys_hf = [k for k in sd_keys_hf if not k.endswith(".attn.bias")]
        transposed = ["attn.c_attn.weight", "attn.c_proj.weight", "mlp.c_fc.weight","mlp.c_proj.weight"]

        assert len(sd_keys_hf) == len(sd_keys), f"mismatched keys: {len(sd_keys_hf)} != {len(sd_keys)}"
        for k in sd_keys_hf:
            if any(k.endswith(w) for w in transposed):
                assert sd_hf[k].shape[::-1] == sd[k].shape
                with torch.no_grad():
                    sd[k].copy_(sd_hf[k].t())
            else:
                assert sd_hf[k].shape == sd[k].shape
                with torch.no_grad():
                    sd[k].copy_(sd_hf[k])
        
        return model
#------------------------------------------------------------------------------
class DataLoaderLite:
    def __init__(self,B,T):
        self.B = B 
        self.T = T 

        with open("input.txt", "r") as f :
            text = f.read()
        enc = tiktoken.get_encoding("gpt2")
        tokens = enc.encode(text)
        self.tokens = torch.tensor(tokens)
        print(f"loaded {len(self.tokens)} tokens")
        print(f"1 epoch = {len(self.tokens) // (B*T)} batches")

        self.current_position=0
    
    def next_batch(self):
        B, T = self.B, self.T
        buf = self.tokens[self.current_position : self.current_position+B*T+1]
        x = (buf[:-1]).view(B,T)
        y = (buf[1:]).view(B,T)

        self.current_position += B * T 
        if self.current_position + (B * T + 1) > len(self.tokens):
            self.current_position = 0
        return x, y


device = "cpu"
if torch.cuda.is_available():
    device = "cuda"
elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
    device ="mps"
print(f"using device : {device}")

train_loader = DataLoaderLite(B=4,T=32)

# get logits
model = GPT(GPTConfig())
model.to(device)

#optimizer
optimizer = torch.optim.AdamW(model.parameters(), lr=3e-4)
for i in range(50):
    x,y = train_loader.next_batch()
    x, y = x.to(device), y.to(device)
    optimizer.zero_grad()
    logits, loss = model(x,y)
    loss.backward()
    optimizer.step()
    print(f"step {i}, loss: {loss.item()}")

logits, loss = model(x,y)

print(loss)
import sys;sys.exit(0)

num_return_sequences = 5
max_lenght = 30

model = GPT.from_pretrained("gpt2")
model.eval()
model.to(device)


torch.manual_seed(42)
torch.cuda.manual_seed(42)
while x.size(1) < max_lenght:
    with torch.no_grad():
        logits = model(x)[0] # (B, T, vocab_size)

        logits = logits[:,-1,:] # (B, vocab_size)
        probs = F.softmax(logits, dim=-1)

        topk_probs, topk_indices  = torch.topk(probs, 50, dim=-1) #(5,50), (5,50)
        ix = torch.multinomial(topk_indices.type(torch.float16),1)
        xcol = torch.gather(topk_indices, -1, ix)
        x = torch.cat((x,xcol), dim=1)

for i in range(num_return_sequences):
    tokens = x[i, :max_lenght].tolist()
    decoded = enc.decode(tokens)
    print(">", decoded)
    print("pull")




    
