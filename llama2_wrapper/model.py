# coding:utf-8
from threading import Thread
from typing import Any, Iterator


class LLAMA2_WRAPPER:
    def __init__(self, config: dict = {}):
        self.config = config
        self.model = None
        self.tokenizer = None

    def init_model(self):
        if self.model is None:
            self.model = LLAMA2_WRAPPER.create_llama2_model(
                self.config,
            )
        if not self.config.get("llama_cpp"):
            self.model.eval()

    def init_tokenizer(self):
        if self.tokenizer is None and not self.config.get("llama_cpp"):
            self.tokenizer = LLAMA2_WRAPPER.create_llama2_tokenizer(self.config)

    @classmethod
    def create_llama2_model(cls, config):
        model_name = config.get("model_name")
        load_in_8bit = config.get("load_in_8bit", True)
        load_in_4bit = config.get("load_in_4bit", False)
        llama_cpp = config.get("llama_cpp", False)
        if llama_cpp:
            from llama_cpp import Llama

            model = Llama(
                model_path=model_name,
                n_ctx=config.get("MAX_INPUT_TOKEN_LENGTH"),
                n_batch=config.get("MAX_INPUT_TOKEN_LENGTH"),
            )
        elif load_in_4bit:
            from auto_gptq import AutoGPTQForCausalLM

            model = AutoGPTQForCausalLM.from_quantized(
                model_name,
                use_safetensors=True,
                trust_remote_code=True,
                device="cuda:0",
                use_triton=False,
                quantize_config=None,
            )
        else:
            import torch
            from transformers import AutoModelForCausalLM

            model = AutoModelForCausalLM.from_pretrained(
                model_name,
                device_map="auto",
                torch_dtype=torch.float16,
                load_in_8bit=load_in_8bit,
            )
        return model

    @classmethod
    def create_llama2_tokenizer(cls, config):
        model_name = config.get("model_name")
        from transformers import AutoTokenizer

        tokenizer = AutoTokenizer.from_pretrained(model_name)
        return tokenizer

    def get_token_length(
        self,
        prompt: str,
    ) -> int:
        if self.config.get("llama_cpp"):
            input_ids = self.model.tokenize(bytes(prompt, "utf-8"))
            return len(input_ids)
        else:
            input_ids = self.tokenizer([prompt], return_tensors="np")["input_ids"]
            return input_ids.shape[-1]

    def get_input_token_length(
        self, message: str, chat_history: list[tuple[str, str]], system_prompt: str
    ) -> int:
        prompt = get_prompt(message, chat_history, system_prompt)

        return self.get_token_length(prompt)

    def generate(
        self,
        prompt: str,
        max_new_tokens: int = 1024,
        temperature: float = 0.8,
        top_p: float = 0.95,
        top_k: int = 50,
    ) -> Iterator[str]:
        if self.config.get("llama_cpp"):
            inputs = self.model.tokenize(bytes(prompt, "utf-8"))
            generate_kwargs = dict(
                top_p=top_p,
                top_k=top_k,
                temp=temperature,
            )

            generator = self.model.generate(inputs, **generate_kwargs)
            outputs = []
            answer_message =''
            new_tokens = []
            for token in generator:
                if token!='</s>':
                    try:
                        new_tokens.append(token)
                        b_text = self.model.detokenize(new_tokens)
                        # b_text = self.model.decode(new_tokens)
                        answer_message+=str(b_text, encoding="utf-8")
                        new_tokens = []
                    except:
                        pass
                else:
                    yield answer_message
                    break

                if 'Human:' in answer_message:
                    answer_message = answer_message.split('Human:')[0]
                    yield answer_message
                    break
                
                if token == self.model.token_eos():
                    yield answer_message
                    break
                
                yield answer_message
        else:
            from transformers import TextIteratorStreamer

            inputs = self.tokenizer([prompt], return_tensors="pt").to("cuda")

            streamer = TextIteratorStreamer(
                self.tokenizer, timeout=10.0, skip_prompt=True, skip_special_tokens=True
            )
            generate_kwargs = dict(
                inputs,
                streamer=streamer,
                max_new_tokens=max_new_tokens,
                do_sample=True,
                top_p=top_p,
                top_k=top_k,
                temperature=temperature,
                num_beams=1,
            )
            t = Thread(target=self.model.generate, kwargs=generate_kwargs)
            t.start()

            outputs = []
            for text in streamer:
                outputs.append(text)
                yield "".join(outputs)

    def run(
        self,
        message: str,
        chat_history: list[tuple[str, str]],
        system_prompt: str,
        max_new_tokens: int = 1024,
        temperature: float = 0.3,
        top_p: float = 0.95,
        top_k: int = 50,
    ) -> Iterator[str]:
        prompt = get_prompt(message, chat_history, system_prompt)
        return self.generate(prompt, max_new_tokens, temperature, top_p, top_k)

    def __call__(
        self,
        prompt: str,
        **kwargs: Any,
    ) -> str:
        if self.config.get("llama_cpp"):
            return self.model.__call__(prompt, **kwargs)["choices"][0]["text"]
        else:
            inputs = self.tokenizer([prompt], return_tensors="pt").input_ids.to("cuda")
            output = self.model.generate(inputs=inputs, **kwargs)
            return self.tokenizer.decode(output[0])


def get_prompt(
    message: str, chat_history: list[tuple[str, str]], system_prompt: str
) -> str:
    prompt = ''
    for user_input, response in chat_history:
        prompt += "<s>Human: " + user_input.strip()+"\n</s><s>Assistant: " + response.strip()+"\n</s>"
        
    prompt += "<s>Human: " + message.strip() +"\n</s><s>Assistant: "
    prompt = prompt[-2048:]
    
    if len(system_prompt)>0:
        prompt = '<s>System: '+system_prompt.strip()+'\n</s>'+ prompt
    return prompt


