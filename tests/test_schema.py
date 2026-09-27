import pytest
from pydantic import ValidationError
from app.schemas import ImageTags

GOOD = '{"subject":"Red Fox","category":"animal","attributes":["orange fur","forest"],"caption":"A red fox in a forest","confidence":0.94}'


def test_valid_output_is_parsed_and_normalised():
    t = ImageTags.model_validate_json(GOOD)
    assert t.subject == "red fox" and t.confidence == 0.94


@pytest.mark.parametrize("bad", [
    '{"subject":"fox"}',                                                              # missing fields
    GOOD.replace("0.94", "1.7"),                                                      # confidence out of range
    GOOD.replace('"animal"', '"spaceship"'),                                          # category not in enum
    GOOD.replace('["orange fur","forest"]', "[]"),                                    # no attributes
    "The image shows a fox.",                                                         # prose, not JSON
])
def test_invalid_model_output_is_never_trusted(bad):
    with pytest.raises(ValidationError):
        ImageTags.model_validate_json(bad)
