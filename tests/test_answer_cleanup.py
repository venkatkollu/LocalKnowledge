from backend.utils import clean_generated_answer, trim_incomplete_tail


def test_strips_leading_reasoning_scaffolding():
    answer = (
        "We need answer user's question using only evidence. "
        "Need cite each factual sentence with bracket label. "
        "The bias terms make up 0.09% of BERTBASE parameters [BitFit.pdf:231-250]."
    )
    assert clean_generated_answer(answer) == (
        "The bias terms make up 0.09% of BERTBASE parameters [BitFit.pdf:231-250]."
    )


def test_strips_reasoning_tags():
    answer = "Matrix B is zero [LoRA.pdf:1-10]."
    assert clean_generated_answer(answer) == "Matrix B is zero [LoRA.pdf:1-10]."


def test_leaves_normal_answers_untouched():
    answer = "DoRA decomposes the weight into magnitude and direction [DoRA.pdf:211-237]."
    assert clean_generated_answer(answer) == answer


def test_trims_answer_cut_at_the_token_limit():
    text = (
        "DoRA decomposes the pretrained weight into magnitude and direction "
        "components, then fine-tunes both [DoRA.pdf:77-101]. The direction "
        "component is updated through LoRA and the answer stops mid"
    )
    assert trim_incomplete_tail(text) == (
        "DoRA decomposes the pretrained weight into magnitude and direction "
        "components, then fine-tunes both [DoRA.pdf:77-101]."
    )
