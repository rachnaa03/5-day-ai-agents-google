# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from app.agent import REDEEMED_DISCOUNT_CODES, redeem_discount_code


def test_redeem_discount_code_success() -> None:
    # Clear the redeemed codes before the test
    REDEEMED_DISCOUNT_CODES.clear()

    # Successful redemption
    result = redeem_discount_code("user123", "WELCOME50")
    assert "Success" in result
    assert "WELCOME50" in result
    assert "user123" in result


def test_redeem_discount_code_unregistered_user() -> None:
    REDEEMED_DISCOUNT_CODES.clear()

    # Unregistered user
    result = redeem_discount_code("unknown_user", "WELCOME50")
    assert "Error" in result
    assert "not a registered user" in result


def test_redeem_discount_code_invalid_code() -> None:
    REDEEMED_DISCOUNT_CODES.clear()

    # Invalid discount code
    result = redeem_discount_code("user123", "INVALIDCODE")
    assert "Error" in result
    assert "invalid" in result


def test_redeem_discount_code_already_redeemed() -> None:
    REDEEMED_DISCOUNT_CODES.clear()

    # First redemption
    result1 = redeem_discount_code("user123", "SUMMER20")
    assert "Success" in result1

    # Second redemption
    result2 = redeem_discount_code("user456", "SUMMER20")
    assert "Error" in result2
    assert "already been redeemed" in result2
