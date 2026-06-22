from transformers import AutoTokenizer, AutoModel
import torch

_tokenizer = None
_model = None


def get_model():
    global _tokenizer, _model

    if _model is None:
        print("🔵 Loading InLegalBERT...")

        _tokenizer = AutoTokenizer.from_pretrained("law-ai/InLegalBERT")
        _model = AutoModel.from_pretrained("law-ai/InLegalBERT")

        _model.eval()

    return _tokenizer, _model


# ---------------------------------------
# MEAN POOLING (IMPORTANT)
# ---------------------------------------
def mean_pooling(model_output, attention_mask):
    token_embeddings = model_output[0]

    input_mask_expanded = attention_mask.unsqueeze(-1).expand(token_embeddings.size()).float()

    return torch.sum(token_embeddings * input_mask_expanded, 1) / torch.clamp(
        input_mask_expanded.sum(1), min=1e-9
    )


# ---------------------------------------
# EMBED TEXTS
# ---------------------------------------
def embed_texts(texts):
    tokenizer, model = get_model()

    embeddings = []

    for text in texts:
        encoded = tokenizer(
            text,
            padding=True,
            truncation=True,
            return_tensors="pt",
            max_length=512
        )

        with torch.no_grad():
            output = model(**encoded)

        emb = mean_pooling(output, encoded["attention_mask"])

        embeddings.append(emb[0].tolist())

    return embeddings


# ---------------------------------------
# EMBED QUERY
# ---------------------------------------
def embed_query(query):
    return embed_texts([query])[0]