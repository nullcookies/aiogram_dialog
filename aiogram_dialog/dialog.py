from logging import getLogger
from typing import Dict, Optional, Union

from aiogram import Dispatcher
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery, ContentTypes
from aiogram.utils.exceptions import MessageNotModified

from .data import DialogData
from .exceptions import StateBrokenError
from .step import Step
from .texts import DialogTexts

logger = getLogger(__name__)


class Dialog:
    def __init__(
            self,
            steps: Dict[State, Step],
            can_cancel: bool = True,
            can_back: bool = True,
            can_done: bool = False,
            can_skip: bool = False,
            internal_callback_prefix: str = "",
            dialog_field: str = "",
            texts: Optional[DialogTexts] = None,

    ):
        self.steps = {
            (s and s.state): step for s, step in steps.items()
        }
        self.states = list(self.steps)

        self.dialog_field = dialog_field

        self.cancel_cd = internal_callback_prefix + "[cancel]"
        self.done_cd = internal_callback_prefix + "[done]"
        self.back_cd = internal_callback_prefix + "[back]"
        self.skip_cd = internal_callback_prefix + "[skip]"

        self._can_cancel = can_cancel
        self._can_back = can_back
        self._can_done = can_done
        self._can_skip = can_skip

        self.finished_callbacks = []
        self.done_callbacks = []
        self.cancel_callbacks = []
        self.texts = texts or DialogTexts()

    def can_cancel(self, step: Optional[Step]) -> bool:
        if not step:
            return self._can_cancel
        return self._can_cancel and step.can_cancel()

    def can_back(self, state: str, step: Optional[Step]) -> bool:
        if not step:
            return False
        if self.states.index(state) < 1:
            return False
        return self._can_back and step.can_back()

    def can_done(self, step: Optional[Step]) -> bool:
        if not step:
            return self._can_done
        return self._can_done and step.can_done()

    def can_skip(self, step: Optional[Step]) -> bool:
        if not step:
            return self._can_skip
        return self._can_skip and step.can_skip()

    def add_finished_callback(self, callback):
        self.finished_callbacks.append(callback)

    def add_done_callback(self, callback):
        self.done_callbacks.append(callback)

    def add_cancel_callback(self, callback):
        self.cancel_callbacks.append(callback)

    async def on_done(self, m: Message, dialog_data: Dict, *args, **kwargs):
        pass

    async def done(self, m: Message, dialog_data: DialogData, args, kwargs):
        data = await dialog_data.data()
        await self._do_finish(m, dialog_data)
        await self.on_done(m, dialog_data=data, *args, **kwargs)
        for c in self.done_callbacks:
            await c(m, dialog_data=data, *args, **kwargs)
        await self._notify_finish(m, args, kwargs)

    async def on_cancel(self, m: Message, *args, **kwargs):
        pass

    async def cancel(self, m: Message, dialog_data: DialogData, args, kwargs):
        await self._do_finish(m, dialog_data)
        await self.on_cancel(m, *args, **kwargs)
        for c in self.cancel_callbacks:
            await c(m, *args, **kwargs)
        await self._notify_finish(m, args, kwargs)

    async def on_finish(self, m: Message, *args, **kwargs):
        pass

    async def _do_finish(self, m: Message, dialog_data: DialogData):
        oldmsg_id = await dialog_data.message_id()
        if oldmsg_id:
            try:
                await m.bot.edit_message_reply_markup(chat_id=m.chat.id, message_id=oldmsg_id)
            except MessageNotModified:
                pass
        await dialog_data.reset()

    async def _notify_finish(self, m: Message, args, kwargs):
        await self.on_finish(m, *args, **kwargs)
        for c in self.finished_callbacks:
            await c(m, *args, **kwargs)

    async def on_start(self, m: Message, *args, **kwargs):
        pass

    async def start(self, m: Message, state: FSMContext, dialog_data: Optional = None, next_state: str = NotImplemented,
                    *args, **kwargs):
        real_dialog_data = DialogData(self.dialog_field, state)
        real_dialog_data.update(dialog_data)
        await real_dialog_data.set_old_state()
        await self.on_start(m, *args, **kwargs)
        if next_state is NotImplemented:
            next_state = self.next_step(None)
        await self.switch_step(m, real_dialog_data, None, next_state, self.steps[next_state], False, args, kwargs)
        await real_dialog_data.commit()

    async def on_back(self, m: Message, *args, **kwargs):
        pass

    async def back(self, c: CallbackQuery, dialog_data: DialogData, args, kwargs):
        current_state = await dialog_data.state.get_state()
        current_step: Step = self.steps[current_state]
        await self.on_back(c.message, *args, **kwargs)
        if current_step:
            del dialog_data[current_step.field()]
        prev_state = current_step.back
        if prev_state is NotImplemented:
            prev_state = self.states[self.states.index(current_state) - 1]
        prev_step = self.steps[prev_state]
        await self.switch_step(c.message, dialog_data, None, prev_state, prev_step, True, args, kwargs)
        await dialog_data.commit()

    async def on_next(self, m: Message, *args, **kwargs):
        pass

    async def next(self, current_state: str, m: Message, dialog_data: DialogData, edit: bool,
                   error: Optional[Exception], next_state: Union[str, "Dialog", None],
                   args, kwargs):
        await self.on_next(m, args, kwargs)
        if isinstance(next_state, State):
            next_state = next_state.state
        if next_state is NotImplemented:
            next_state = self.next_step(current_state)
        if isinstance(next_state, Dialog):
            await self.switch_dialog(m, dialog_data, next_state, args, kwargs)
            return

        if not next_state:
            await self.done(m, dialog_data, args, kwargs)
        else:
            await self.switch_step(m, dialog_data, error, next_state, self.steps[next_state], edit, args, kwargs)

    async def get_kbd(self, current_state: str, current_step: Step, current_data: Dict, args, kwargs):
        kbd = await current_step.render_kbd(current_data, *args, **kwargs)
        if not kbd:
            kbd = InlineKeyboardMarkup()
        steps_row = []
        if self.can_back(current_state, current_step):
            steps_row.append(InlineKeyboardButton(text=self.texts.back, callback_data=self.back_cd))
        if self.can_skip(current_step):
            steps_row.append(InlineKeyboardButton(text=self.texts.skip, callback_data=self.skip_cd))
        if steps_row:
            kbd.row(*steps_row)
        finish_row = []
        if self.can_cancel(current_step):
            finish_row.append(InlineKeyboardButton(text=self.texts.cancel, callback_data=self.cancel_cd))
        if self.can_done(current_step):
            finish_row.append(InlineKeyboardButton(text=self.texts.done, callback_data=self.done_cd))
        if finish_row:
            kbd.row(*finish_row)
        return kbd

    def next_step(self, current_state: Optional[str]) -> Optional[str]:
        if not current_state:
            return self.states[0]
        try:
            return self.states[self.states.index(current_state) + 1]
        except IndexError:
            return

    async def handle_message(self, m: Message, *args, **kwargs):
        state: FSMContext = kwargs["state"]
        dialog_data = DialogData(self.dialog_field, state)
        current_state = await state.get_state()
        step: Step = self.steps.get(current_state)
        if not step:
            logger.error("Not step found for current state `%s`. Probably steps changed after registration",
                         current_state)
            raise StateBrokenError(f"No step found for state {current_state}")

        data = await dialog_data.data()
        try:
            value, next_state = await step.process_message(m, data, *args, **kwargs)
            dialog_data[step.field()] = value
            error = None
        except ValueError as e:
            next_state = current_state
            error = e

        edit = (next_state == current_state)  # if step did not changed only edit message
        await self.next(current_state, m, dialog_data, edit, error, next_state, args, kwargs)
        await dialog_data.commit()

    async def handle_callback(self, c: CallbackQuery, *args, **kwargs):
        state: FSMContext = kwargs["state"]
        dialog_data = DialogData(self.dialog_field, state)
        current_state = await state.get_state()

        if c.data == self.done_cd:
            await self.done(c.message, dialog_data, args, kwargs)
            await c.answer()
            return
        elif c.data == self.back_cd:
            await self.back(c, dialog_data, args, kwargs)
            await c.answer()
            return
        elif c.data == self.skip_cd:
            await self.next(current_state, c.message, dialog_data, True, None, NotImplemented, args, kwargs)
            await c.answer()
            return
        elif c.data == self.cancel_cd:
            await self.cancel(c.message, dialog_data, args, kwargs)
            await c.answer()
            return

        step = self.steps.get(current_state)
        if not step:
            logger.error("Not step found for current state `%s`. Probably steps changed after registration",
                         current_state)
            raise StateBrokenError(f"No step found for state {current_state}")

        data = await dialog_data.data()
        try:
            value, next_state = await step.process_callback(c, data, *args, **kwargs)
            dialog_data[step.field()] = value
            error = None
        except ValueError as e:
            next_state = current_state
            error = e

        await self.next(current_state, c.message, dialog_data, True, error, next_state, args, kwargs)
        await c.answer()
        await dialog_data.commit()

    async def switch_step(self,
                          message: Message,
                          dialog_data: DialogData,
                          error: Optional[Exception],
                          next_state: str,
                          next_step: Step,
                          edit: bool,
                          args, kwargs):
        oldmsg_id = await dialog_data.message_id()
        data = await dialog_data.data()
        new_text = await next_step.render_text(data, error, *args, **kwargs)
        if edit and oldmsg_id:
            if message.text != new_text:
                await message.bot.edit_message_text(
                    chat_id=message.chat.id, message_id=oldmsg_id,
                    text=new_text
                )
            try:
                await message.bot.edit_message_reply_markup(
                    chat_id=message.chat.id, message_id=oldmsg_id,
                    reply_markup=await self.get_kbd(next_state, next_step, data, args, kwargs)
                )
            except MessageNotModified:
                pass
        else:
            if oldmsg_id:
                try:
                    await message.bot.edit_message_reply_markup(
                        chat_id=message.chat.id,
                        message_id=oldmsg_id
                    )
                except MessageNotModified:
                    pass
            newmsg = await message.answer(
                text=new_text,
                reply_markup=await self.get_kbd(next_state, next_step, data, args, kwargs),
            )
            dialog_data.set_message_id(newmsg.message_id)
        await dialog_data.state.set_state(next_state)

    async def switch_dialog(self, message: Message, dialog_data: DialogData, dialog: "Dialog", args, kwargs):
        oldmsg_id = await dialog_data.message_id()
        if oldmsg_id:
            try:
                await message.bot.edit_message_reply_markup(
                    chat_id=message.chat.id, message_id=oldmsg_id
                )
            except MessageNotModified:
                pass
        await self.start_dialog(message, dialog_data, dialog, args, kwargs)

    async def start_dialog(self, m: Message, dialog_data: DialogData, dialog: "Dialog", args, kwargs):
        await dialog.start(m, *args, **kwargs)

    async def on_resume(self, m: Message, *args, **kwargs):
        pass

    async def resume(self, message: Message, *args, **kwargs) -> bool:
        state: FSMContext = kwargs["state"]
        dialog_data = DialogData(self.dialog_field, state)

        data = await dialog_data.data()
        next_state = await state.get_state()
        if next_state not in self.steps:
            return False
        next_step = self.steps[next_state]
        if not next_step:
            print("!!!!!! No step")

        await self.on_resume(message, *args, **kwargs)

        newmsg = await message.answer(
            text=await next_step.render_text(data, None, *args, **kwargs),
            reply_markup=await self.get_kbd(next_state, next_step, data, args, kwargs),
        )
        dialog_data.set_message_id(newmsg.message_id)
        await dialog_data.commit()
        return True

    def register_handler(self, dp: Dispatcher, *args, **kwargs):
        dp.register_message_handler(self.handle_message,
                                    state=self.states, content_types=ContentTypes.ANY,
                                    *args, **kwargs)
        dp.register_callback_query_handler(self.handle_callback, state=self.states, *args, **kwargs)


class SimpleDialog(Dialog):
    def __init__(self, state: State, step: Step, can_cancel: bool = True,
                 internal_callback_prefix: str = "",
                 dialog_field: str = ""):
        super().__init__(
            steps={state: step},
            can_skip=False,
            can_done=False,
            can_cancel=can_cancel,
            can_back=False,
            dialog_field=dialog_field,
            internal_callback_prefix=internal_callback_prefix,
        )
