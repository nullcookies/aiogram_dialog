from itertools import chain
from typing import List, Callable, Optional, Union

from aiogram.types import InlineKeyboardButton

from .text import Text
from .when import Whenable


class Keyboard(Whenable):
    def __init__(self, when: Union[str, Callable] = None):
        super(Keyboard, self).__init__(when)

    async def render_kbd(self, data) -> List[List[InlineKeyboardButton]]:
        if not self.is_(data):
            return []
        return await self._render_kbd(data)

    async def _render_kbd(self, data) -> List[List[InlineKeyboardButton]]:
        raise NotImplementedError


class Button(Keyboard):
    def __init__(self, text: Text, callback_data: Text, on_click: Optional[Callable] = None,
                 when: Union[str, Callable] = None):
        super().__init__(when)
        self.text = text
        self.callback_data = callback_data
        self.on_click = on_click

    async def _render_kbd(self, data) -> List[List[InlineKeyboardButton]]:
        return [[
            InlineKeyboardButton(
                text=await self.text.render_text(data),
                callback_data=await self.callback_data.render_text(data)
            )
        ]]


class Uri(Keyboard):
    def __init__(self, text: Text, uri: Text, when: Union[str, Callable, None] = None):
        super().__init__(when)
        self.text = text
        self.uri = uri

    async def _render_kbd(self, data) -> List[List[InlineKeyboardButton]]:
        return [[
            InlineKeyboardButton(
                text=await self.text.render_text(data),
                uri=await self.uri.render_text(data)
            )
        ]]


class Group(Keyboard):
    def __init__(self, *buttons: Keyboard, keep_rows: bool = True, width: int = 0,
                 when: Union[str, Callable, None] = None):
        super().__init__(when)
        self.buttons = buttons
        self.keep_rows = keep_rows
        self.width = width

    async def _render_kbd(self, data) -> List[List[InlineKeyboardButton]]:
        kbd: List[List[InlineKeyboardButton]] = []
        for b in self.buttons:
            b_kbd = await b.render_kbd(data)
            if self.keep_rows or not kbd:
                kbd += b_kbd
            else:
                kbd[0].extend(chain.from_iterable(b_kbd))
        if not self.keep_rows and self.width:
            kbd = self._wrap_kbd(kbd[0])
        return kbd

    def _wrap_kbd(self, kbd: List[InlineKeyboardButton]) -> List[List[InlineKeyboardButton]]:
        res: List[List[InlineKeyboardButton]] = []
        row: List[InlineKeyboardButton] = []
        for b in kbd:
            row.append(b)
            if len(row) >= self.width:
                res.append(row)
                row = []
        if row:
            res.append(row)
        return res