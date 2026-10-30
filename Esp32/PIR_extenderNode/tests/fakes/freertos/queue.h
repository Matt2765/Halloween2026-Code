#pragma once
struct FakeQueue {size_t capacity,size;std::deque<std::vector<uint8_t>> items;};
using QueueHandle_t=FakeQueue*;
inline QueueHandle_t xQueueCreate(size_t capacity,size_t size){return new FakeQueue{capacity,size,{}};}
inline int xQueueSend(QueueHandle_t q,const void* data,int){if(q->items.size()>=q->capacity)return 0;auto p=(const uint8_t*)data;q->items.emplace_back(p,p+q->size);return pdTRUE;}
inline int xQueueReceive(QueueHandle_t q,void* data,int){if(q->items.empty())return 0;memcpy(data,q->items.front().data(),q->size);q->items.pop_front();return pdTRUE;}
inline size_t uxQueueMessagesWaiting(QueueHandle_t q){return q->items.size();}
