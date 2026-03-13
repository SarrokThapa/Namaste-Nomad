from channels.generic.websocket import AsyncJsonWebsocketConsumer


class NotificationConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        user = self.scope.get('user')
        if not user or user.is_anonymous:
            await self.close()
            return

        self.group_name = f'notifications_{user.id}'
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        user = self.scope.get('user')
        if not user or user.is_anonymous:
            return
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def notification_message(self, event):
        payload = event.get('payload', {})
        await self.send_json(payload)
